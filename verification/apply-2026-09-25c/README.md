# Stage 2B-i (2026-09-25): code fixes and the held001 batch

This folder applies the 30 edits that stage 2A held
([../apply-2026-09-25b/README.md](../apply-2026-09-25b/README.md), `classes001-proposals.json`
`skipped`). It follows the rules in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md): keys follow
corrected metadata (user), every rename is logged in [../key-renames.json](../key-renames.json), and the
house address form `City, {ST}` stays. The address rule, like the surname-corroboration rule that
keeps RuggEtal96 held, was Claude's and awaits the user's confirmation (resolution-plan README,
"Rules Claude adopted").

Library counts come from `bibcheck.py crossref status cdl.bib` (metadata_verified / needs_review, of 6,422).

| Step | Entries | Result | Requests (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|
| start | | | | 4,373 / 2,049 | 1c1c13a |
| code fixes + key-renames.json | | 1,463 tests pass | 0 | unchanged | 47f5b79 |
| held001 | 25 edits, 12 key renames | 23 / 25 verified | 30 / 0 (83 / 0 review writes) | 4,396 / 2,026 | 12ede17 |

## 1. Code fixes (tests first, in `tests/test_machinery_2026_09_25.py`, section 14)

- **Edited volumes key on editors.** `helpers.key_names` gives the ID rule the editors when an
  entry has no author, so an edited volume gets `SchaTulv94` rather than the year-only `94`. The
  suffix rule uses the same names, so `MeltMart72` and `TulvDona72` no longer collide as
  `72a`/`72b`. The tests also show that an entry with an author and editors still keys on the
  author, that a wrong key is still rejected with the editor-based target, and that editor keys
  get a/b suffixes like any other key. No current cdl.bib entry lacks an author, so the change
  does not affect existing keys.
- **Dotted publisher initials.** `format_journal_name(..., dotted_initials=True)` is used only for
  `publisher` and keeps words made of capital initials and periods (`W.H.`, `V.`, `D.C.`)
  as written. Marr82's "W.H. Freeman" had been rewritten as "W.h. Freeman". The existing house
  forms (`{W}. {H}. Freeman`, `{D}. Appleton and Company`) still pass. Lowercase input is still
  formatted, publisher aliases still apply, and journal names are unchanged, because the flag is off
  for them.
- **`verify --recheck-cached` keeps valid route approvals.** `run_verification` rechecks a saved
  approval with `auto_review.reassess`, which only rebuilds decisions from Crossref, PubMed, JATS
  and the built-in layers. It used to reopen FranLiu18's `osf-repository` approval, which the OSF
  route then approved again on every run. Now, when reassess would reopen a row that a route validator
  (`verification.route_approval_valid`: the registered OSF, DataCite, ACL and SfN validators and the
  built-in arXiv/catalogue/preprint ones) still accepts from its saved evidence, the row is kept.
  - The FranLiu18 recheck (real OSF documents from
    `../routes-2026-09-25/fixtures/osf_review.json`) stays verified with 0 requests and 0 writes.
  - Negative control: a tampered approval is still reopened.
  - An arXiv approval (PianHill22) stays verified.
  - Before the fix, a live check of all 4,373 verified entries found FranLiu18 was the only one that
    reassess reopens.

## 2. `../key-renames.json`

A list of `{old_key, new_key, date, reason, commit}` records, starting with the two classes001
renames (bac94e6), followed by the 12 held001 renames below.

## 3. held001

[`build_held.py`](build_held.py) takes the 30 held rows and builds `held001-proposals.json` under
these rules. The values are always the source-stated ones; only their form changes.

- **Year, first-author and author-count changes rename the key.** The ID rule gives the new key,
  and each new key was checked unused in cdl.bib, including with suffixes.
- **Editions** use the house form: Howe97 `4\textsuperscript{th}`, and Klin05 and RoseRosn91
  `2\textsuperscript{nd}`.
- **HastEtal01's title** drops LoC's ISBD " : " and the statement "with 200 full-color
  illustrations". The result is "The elements of statistical learning: data mining, inference, and prediction".
- **vandGlas00's editors** are written with initials: "W J van der Linden and C A W Glas".
- **Free75** keeps `{EEG}` braced.
- **Marr82** gets "W.H. Freeman", which the fixed formatter accepts. MeltMart72 gets "V. H. Winston".
- **Catalogue address edits.**
  - An L-class edit that only removes the house `{ST}`/`{UK}` suffix is dropped. This covers Tulv83,
    Galt83, Buzs06 and OKeeNade78 whole, and the address part of Carr93, whose author fix J D → J B
    Carroll is kept.
  - A catalogue *city* change is kept in house form: UndeShul60 "Chicago, {IL}" and TulvDona72
    "New York, {NY}".
- **RuggEtal96 stays held.** The single-source surname change Patchin → Patching has no corroboration.

`helpers.check_bib` accepted all 25 kept proposals, with their renames. The run used
[`apply.py`](apply.py), which is the `../apply-2026-09-25b/apply.py` runner with this folder's
paths. Its pipeline ends in `verify --recheck-cached`, which is now safe for route approvals.

- The staging diff was limited to the 25 entries and their 12 renames, and `check_bib` was clean.
- The backup and snapshot are in `.bibcheck/apply-2026-09-25c/`.
- Run: 30 requests and 83 review writes, 906 s.
- Repeat: 0 requests and 0 writes, with identical results.
- No accepted result outside the batch changed, and nothing else was newly verified.

**Verified (23):**

- **Crossref (8):** BonhGrin91, HillAnll98, KounEtal94, LangEtal01, Lewi97, OpdeEtal08, SiroDas09,
  SmitEtal99.
- **Europe PMC (2):** RotsEtal05 and SchlEtal08.
- **LoC catalogue (13):** Cowa95, Free75, HorcDhil04, Howe97, Klin05, Marr82, MeltMart72,
  MiyaShah99, RoseRosn91, SchaTulv94, TulvDona72, UndeSchu60 and vandGlas00.

**Applied but still needs_review (2):**

- **HastEtal01**: "No unique, fully matching catalogue edition", with `title: missing evidence or mismatch`.
  The catalogue comparator wants LoC's full title, including the statement of responsibility,
  which the user's rule removes.
- **Carr93**: the same catalogue issue, with `address: missing evidence or mismatch`. Its author
  correction (J B Carroll) is applied.

**Key renames (12, logged in `../key-renames.json`):**

| Old key | New key |
|-|-|
| Lewi10 | Lewi97 |
| SiroDas08 | SiroDas09 |
| SchlEtal07 | SchlEtal08 |
| RotsEtal04 | RotsEtal05 |
| Cowa97 | Cowa95 |
| HillLour98 | HillAnll98 |
| deBeEtal08 | OpdeEtal08 |
| BonhEtal91 | BonhGrin91 |
| UndeShul60 | UndeSchu60 |
| Lang01 | LangEtal01 |
| GeviEtal99 | SmitEtal99 |
| Koun94 | KounEtal94 |

Papers that cite the old keys must be updated.

**Still held:**

- RuggEtal96, by the surname guard.
- The four dropped L-class edits, which are not applied by rule.

## Checks after held001

- `.bibcheck/validate-current-checkpoint.py`, which now reads the renames from `key-renames.json`
  and compares against `held001-staged.bib`: 6,422 restored, 0 repeat imports, SQLite `quick_check`
  ok.
- `verification/benchmark/run.py` `run()`: 60/60, with 0 false acceptances and 0 missed matches.
- Full pytest: 1,463 passed.
- `bibcheck.py verify`: "looks good!".
- `bibcheck.py crossref status cdl.bib`: 4,396 metadata_verified / 2,026 needs_review.

## Reproduce

```
.venv/bin/python verification/apply-2026-09-25c/build_held.py
.venv/bin/python verification/apply-2026-09-25c/apply.py held001 [--apply]
.venv/bin/python .bibcheck/validate-current-checkpoint.py
```
