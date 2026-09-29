# Stage 2A batches (2026-09-26)

This folder applies two batches to `cdl.bib` with [`apply.py`](apply.py), following the
decisions in [../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md).
The batch discipline is the one used in [../apply-2026-09-23/](../apply-2026-09-23/README.md)
and [../apply-2026-09-25/](../apply-2026-09-25/README.md):

1. Freeze the proposals, or the keys for a no-edit batch, with their fingerprints.
2. Check the staging diff: it must be limited to the batch and pass `helpers.check_bib`.
3. Take a backup and a snapshot under `.bibcheck/apply-2026-09-26/`.
4. Apply the batch, then run the production pipeline on the batch keys.
5. Run the pipeline again. The repeat must make 0 network requests and 0 review writes.
6. Check that no accepted result outside the batch changed.
7. Export `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz`.
8. Run the fresh-restore check (`.bibcheck/validate-current-checkpoint.py`).
9. Run the full pytest suite and the benchmark.

Library counts are `bibcheck.py crossref status cdl.bib` (metadata_verified / needs_review, of 6,422).

| Step | Entries | Result | Requests (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|
| start | | | | 4,034 / 2,388 | deb0f61 |
| reassess002 (no edit) | 2,388 | 19 newly verified | 65 / 0 (0 writes) | 4,053 / 2,369 | 28ea4dd |
| proposal regeneration (read-only) | 2,369 | 334 article + 48 catalogue proposals | 0 | unchanged | with classes001 |
| classes001 | 320 edits, 2 key renames | 320 / 320 verified | 265 / 0 (0 writes) | 4,373 / 2,049 | see git log |

After each batch:

- the fresh restore was exact: 6,422 restored, 0 repeat imports, and SQLite `quick_check` returned ok;
- `verification/benchmark/run.py` (called through `run()`) passed 60/60, with 0 false
  acceptances and 0 missed matches;
- the full pytest suite passed 1,447 tests after reassess002. After classes001, 1,446
  passed and 1 failed (see below).
- `bibcheck.py verify` printed "looks good!" after classes001.

**Test broken by classes001 (reported, not edited):**
`tests/test_pdf_evidence.py::test_hyphenated_title_is_not_the_unhyphenated_print`.

- The test reads KahaJaco00 from the live `cdl.bib`, because that key is not frozen in
  `verification/pdf-benchmark/cases.json`.
- It expects the cited title "Inter-response times ..." to differ from the PDF's
  "Interresponse".
- classes001 applied the approved S1-TITLE-CROSSREF-ONLY correction to "Interresponse times ...".
  This is Crossref's title, and it matches the printed PDF, so the verifier now correctly
  supports the title.
- The fix belongs in the test: freeze KahaJaco00's pre-correction fields as a benchmark case,
  or pass the hyphenated title explicitly. That file is owned by the PDF-evidence work.

## 1. reassess002: production `verify --auto-review` over every needs_review entry

The batch covered all 2,388 needs_review entries (frozen in `reassess002-proposals.json`). It ran
the production CLI path (`bibcheck/verification_cli.py verify --auto-review`) in this order:

- verify;
- the auto-review, full-text, PMC, publisher-year, catalogue, preprint and arXiv layers;
- the four 2026-09-25 routes: OSF, DataCite, ACL Anthology and SfN.

No BibTeX was edited.

**Result: 19 newly verified, against a prediction of at least 18.** All 18 keys that
[../machinery-2026-09-25/newly-verifiable.json](../machinery-2026-09-25/newly-verifiable.json)
predicts verified:

- BradLang00, DaviDavi12, Feyn65, GilmEtal79 and HogeEtal99;
- JonaKord17, LeeEtal21, Mada21, MeyeEtal88 and NguyEtal22;
- NieuEtal01, NoldEtal98, SawrEtal96 and SchaEtal11;
- StJaEtal08, StJaEtal12, StJaScha13 and WangEtal19.

The routes added FranLiu18 (OSF, `10.31234/osf.io/bucqx`). This is the only route verification
that [../routes-2026-09-25/measurement.json](../routes-2026-09-25/measurement.json) predicts
for cdl.bib. FitzEtal26a, Spee22 and ReimGure19 are PR #87/#88 fixtures and are not in cdl.bib, so
they could not verify here. No other route verification was expected, and none happened. No
previously accepted result changed.

The per-key results are in `reassess002-results.json`.

**Deviations and fixes (all in files owned by this batch):**

- **Attempt 1** stopped on the ACL route's OpenAlex title search with HTTP 429 ("Anonymous
  search is temporarily rate-limited ... retry in 38s"). It had made 1 request.
  `apply.py` now retries a route after 60 s on HTTP 429 only, up to six times. Every other
  provider error still stops the batch.
- **Attempt 2** made 64 requests, and the run cycle verified the 18 predicted keys. The
  repeat then added 2 review rows and changed results, so the batch failed. The cause was
  that the batch pipeline ended with `verify --recheck-cached`. `verify_entry`'s recheck
  re-derives a saved approval from Crossref evidence only, so it reopens FranLiu18's
  `osf-repository` approval. The OSF route then re-approves it on every run, and the
  pipeline never reaches a fixed point.
- **Attempt 3** used the CLI default (no `--recheck-cached`). The run cycle made 0 requests
  and 1 write (FranLiu18). The repeat made 0 requests and 0 writes and gave identical
  results. The attempt-2 run is kept in `reassess002-first-run.json`.
- **Needs a code change (not in this batch's files):** `run_verification(...,
  recheck_cached=True)` should keep a route approval that `verification.route_approval_valid`
  accepts, instead of reopening it. Until then, `bibcheck.py crossref verify --recheck-cached`
  reopens the route approvals. The shared `pipeline()` in `../apply-2026-09-23/apply.py`
  still uses the recheck, which is safe only while no batch key is route-approved.
  `pipeline()` now also runs the four routes after arXiv, as the CLI does.

## 2. Regenerated proposals (resolver 30)

[`regen.py`](regen.py) runs `../fixes-2026-09-24/measure.py` and
`../catalogue-phase0-2026-09-22/measure.py` unchanged over the post-reassess002 library.
Both open the cache read-only. The outputs are:

- `proposals.json`, `groups.json`, `lookups.json` and `diff.json`, in the fixes-2026-09-24
  schema, with `stated_by`;
- `catalogue/proposals.json` and `catalogue/groups.json`.

The issue lookups used a copy of the lookup cache and made 0 requests: all 10 DOIs were
already stored.

The first run produced 19 `FileNotFoundError` rows. Phase 0 measure copies non-Phase-0
modules into a temporary folder, where `correction_proposals.LIBRARY_BIB` (`../cdl.bib`,
used for surname corroboration) does not exist. The failing entries were the
surname-change cases, among them CleeMcCl91, DoesEtal08, MartJohn15 and RebeEtal02.
`regen.py` now loads every module from the working tree, after checking that `bibcheck/`
equals HEAD, and reran the measurement. The rerun had no error rows and no regressions
among verified entries. FranLiu18 is reported only because the offline reassessment does
not run the OSF route.

Articles: 334 proposals and 2,035 held. The table compares them with
`../fixes-2026-09-24/proposals.json`.

| Class | Unchanged | Changed | New | Withdrawn |
|-|-|-|-|-|
| TWO-SOURCE | 110 | 2 | 6 | 1 |
| S1-PAGES-COMPLETE | 37 | 0 | 1 | 10 |
| S1-JOURNAL-HISTORY-OR-TYPO | 32 | 0 | 2 | 1 |
| S1-TITLE-CROSSREF-ONLY | 31 | 0 | 0 | 0 |
| S1-AUTHOR-NAMES | 28 | 0 | 0 | 11 |
| S1-TWO-FIELDS | 23 | 1 | 1 | 6 |
| S1-COORDINATES | 18 | 0 | 0 | 3 |
| A1b-ARTICLE-NUMBER | 15 | 0 | 0 | 0 |
| S1-TITLE-CORROBORATED | 12 | 0 | 0 | 0 |
| S1-JOURNAL-REPLACEMENT | 6 | 0 | 0 | 0 |
| S1-AUTHOR-SURNAME | 4 | 0 | 0 | 2 |
| S1-TWO-FIELDS-RISKY | 2 | 0 | 3 | 85 (applied in risky001) |

Most withdrawals are entries that are verified now, or entries held by the stage-1 guards.
`diff.json` lists every key.

- **New:** AzizEtal91, Faga70, GellEtal14, HambEtal05, HameChid08, McInJirs19,
  MullEtal87, Murd68, MurdVomS67, OwenEtal20, RegeEtal18, WatsPell83 and WoodMurd68.
- **Changed:**
  - AltsEtal99 and MullEtal96 changed within TWO-SOURCE.
  - DiazEtal06 moved from S1-TWO-FIELDS to S1-JOURNAL-HISTORY-OR-TYPO, because its author change is gone.

Catalogue: 48 keys (65 rows), compared with the catalogue-phase0 proposals:

- 39 are identical;
- 8 changed: Ande76, GorfHoff87, Huth13, Kohl40, LemoPiet12, Luca83, Prib91 and Zar10;
- 1 is new: DrydMard98;
- 16 were withdrawn, mostly P1 names that the same-firm rule now accepts, and entries verified since.

## 3. classes001: approved classes, identical proposals only

[`select_classes.py`](select_classes.py) builds `classes001-proposals.json`. A regenerated
proposal is applied only when all of the following hold:

- its class is one of the approved classes. These are A1b-ARTICLE-NUMBER, S1-AUTHOR-SURNAME,
  S1-COORDINATES, S1-JOURNAL-HISTORY-OR-TYPO, S1-JOURNAL-REPLACEMENT, S1-TITLE-CORROBORATED,
  S1-TITLE-CROSSREF-ONLY, TWO-SOURCE, S1-AUTHOR-NAMES, S1-PAGES-COMPLETE, S1-TWO-FIELDS and
  S1-TWO-FIELDS-RISKY, plus the catalogue classes A1, A2, D, E, L, P2, T and Y;
- its `changes` are identical to the approved fixes-2026-09-24 or catalogue-phase0 version;
- its fingerprint is current;
- no guard holds it (see below).

Holds (30, listed under `skipped` with reasons):

- **Stage-1 guards.** RuggEtal96 is held: the single-source surname change Patchin →
  Patching has no corroboration.
  - No selected proposal shortens a page range or writes a name suffix.
- **Year changes without an approved rename (5).** Lewi10, SiroDas08, SchlEtal07, RotsEtal04
  and Cowa97 change `year`, so each cite key would have to change. Only GautEtal18 and
  HayeEtal14 have an approved rename.
- **House form (5).**
  - Howe97, Klin05 and RoseRosn91 would set `edition` to a bare number, where the house
    form is `N\textsuperscript{th}`.
  - HastEtal01's title keeps LC's " : " separator.
  - vandGlas00's editor has full given names.
- **House formatter (19).** `helpers.check_bib` rejects the edited entry:
  - The key the ID rule demands changes. This happens when the first author changes or is
    added (HillLour98 → HillAnll98, deBeEtal08 → OpdeEtal08, GeviEtal99 → SmitEtal99), when
    the author count changes (BonhEtal91, Lang01, Koun94, UndeShul60), or when author becomes
    editor (SchaTulv94, MiyaShah99, HorcDhil04, TulvDona72, MeltMart72: the rule has no
    author, so it demands `94`, `99`, `04`, `72a`, `72b`).
  - The formatter rewrites the value. The address rule re-adds ` {NY}`/` {UK}` (Tulv83,
    Carr93, Galt83, Buzs06, OKeeNade78, the L class). `publisher` becomes `W.h. Freeman`
    (Marr82). `{EEG}` is braced (Free75).

  Applying any of these needs a user decision: a key rename, or a change to the
  formatter's address rule. The L-class "drop the state or country" edits conflict with the
  formatter as it stands.

**Applied: 320 entries, all 320 now metadata_verified:**

- TWO-SOURCE 103, S1-PAGES-COMPLETE 36, S1-JOURNAL-HISTORY-OR-TYPO 32,
  S1-TITLE-CROSSREF-ONLY 31, S1-AUTHOR-NAMES 28, S1-TWO-FIELDS 23, S1-COORDINATES 17,
  A1b 15, S1-TITLE-CORROBORATED 12, S1-JOURNAL-REPLACEMENT 5, S1-AUTHOR-SURNAME 3 and
  S1-TWO-FIELDS-RISKY 2;
- catalogue: T 7, P2 2, A1 1, A1+P2 1, A2 1 and A2+T 1.

**Key renames (user decision 2026-09-24 23:35 EDT, "Rename keys"):**

- GautEtal18 → **GautEtal19**: title fixed, year 2019.
- HayeEtal14 → **HayeEtal16**: journal "The Journals of Gerontology: Series {B}", year 2016.

Before the batch, neither new key occurred anywhere in cdl.bib. The repository does not
track renames: `bibcheck/key_overrides.json` only lists keys that are exempt from the ID rule.
So the renames are recorded here and in `classes001-proposals.json` (`renames`). Papers that
cite GautEtal18 or HayeEtal14 must be updated. `.bibcheck/validate-current-checkpoint.py`
now accepts the renamed key set. It also imports the route modules, so that their
approvals restore.

## needs-spotcheck.json: 25 new or changed proposals (not applied)

| Class | Count | Keys |
|-|-|-|
| TWO-SOURCE | 8 | McInJirs19, RegeEtal18 (also a year change), OwenEtal20, GellEtal14, MullEtal96, WoodMurd68, MullEtal87, AltsEtal99 |
| S1-TWO-FIELDS-RISKY | 3 | HameChid08 (year change), Faga70, WatsPell83 |
| S1-JOURNAL-HISTORY-OR-TYPO | 3 | Murd68, MurdVomS67, DiazEtal06 |
| S1-PAGES-COMPLETE | 1 | HambEtal05 |
| S1-TWO-FIELDS | 1 | AzizEtal91 |
| catalogue A1 | 2 | Kohl40, Prib91 |
| catalogue E | 2 | GorfHoff87, LemoPiet12 |
| catalogue T | 2 | Ande76, Huth13 |
| catalogue A1+L | 1 | DrydMard98 |
| catalogue D | 1 | Zar10 |
| catalogue Y | 1 | Luca83 |

Each row has the key, class, changes, `stated_by` and the approved version where there was
one. There were 14 new and 11 changed. Seven catalogue P1 proposals (Gibs84, Keme72,
Koff35, MillEtal60, Ripl81, Wood38, Yate66) are unchanged but P1 is not an approved class;
they are listed under `skipped.class_not_approved`.

## Reproduce

```
.venv/bin/python verification/apply-2026-09-26/apply.py reassess002 [--apply]
.venv/bin/python verification/apply-2026-09-26/regen.py articles
.venv/bin/python verification/apply-2026-09-26/regen.py catalogue
.venv/bin/python verification/apply-2026-09-26/select_classes.py
.venv/bin/python verification/apply-2026-09-26/apply.py classes001 [--apply]
.venv/bin/python .bibcheck/validate-current-checkpoint.py
```
