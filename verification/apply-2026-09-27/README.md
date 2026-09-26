# Stage 2B-ii (2026-09-27): house-form batches and DOIs

These batches apply the user's form decisions from
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md):

- no name suffixes;
- initials everywhere;
- issue ranges written `3--4`;
- proceedings names without the year;
- `@book` entries have no pages;
- editions and every other numeric ordinal written `N\textsuperscript{..}` (user, 2026-09-26);
- publisher initials undotted, `W H Freeman` (user, 2026-09-26);
- DOIs everywhere.

Each batch follows the stage 2A/2B-i discipline:

1. The proposals are frozen with entry fingerprints (`<batch>-proposals.json`).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-27/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0
   review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore.
8. The full pytest suite and `verification/benchmark/run.py` (60/60) must pass, then the
   batch is committed locally.

The runner is [`apply.py`](apply.py), which is `../apply-2026-09-26/apply.py` with this
folder's paths. Proposals come from [`build.py`](build.py) and [`build_adddoi.py`](build_adddoi.py).

Library counts come from `bibcheck.py crossref status cdl.bib` (metadata_verified /
needs_review, out of 6,422).

| Step | Entries | Status change in batch | Requests (run / repeat) | Review writes (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|-|
| start | | | | | 4,396 / 2,026 | 89c5b70 |
| machinery (code only) | | none (offline reassess of all 6,422) | 0 | 0 | 4,396 / 2,026 | 23cc902 |
| formats | 56 | 37 verified stay verified; 19 needs_review unchanged | 17 / 0 | 182 / 0 | 4,396 / 2,026 | 5e9a4f8 |
| suffix-strip | 33 | +2 verified (Sauf75, Stro12); none lost | 13 / 0 | 75 / 0 | 4,398 / 2,024 | e885d8e |
| initials, attempt 1 | 1,149 | stopped by the PMC bulk-hours guard; cdl.bib restored | | | 4,398 / 2,024 | fe36e38 |
| ordinals | 34 | 3 verified stay verified; 31 needs_review unchanged | 32 / 0 | 125 / 0 | 4,398 / 2,024 | c2ceaec |
| adddoi002 | 991 | 991 verified stay verified | 1,071 / 0 | 2,129 / 0 | 4,398 / 2,024 | 83d26ac |
| initials (2026-09-25, 21:07 ET) | 1,142 | 892 verified stay verified; +19 verified; none lost | 7 / 0 | 1,434 / 0 | 4,495 / 1,955 (+31 human_verified, of 6,481) | a4e03de + follow-up |

The batches ran as formats, suffix-strip, ordinals, adddoi002, then initials. formats went
first because the new publisher-initials formatter rejects the old dotted forms, so
`check_bib` would fail on every other batch's staging until they were converted. initials went
last because of the PMC hours (see below).

## Machinery (commit 23cc902; tests in `tests/test_machinery_2026_09_25.py`, section 15)

The tests use real records frozen from the committed baseline by [`build_cases.py`](build_cases.py)
([`cases.json.gz`](cases.json.gz)). Every rule has negative controls.

- **House ordinals.** `verification.normalized` reads `30\textsuperscript{th}` as `30th`. It reads
  only a number followed by `st`, `nd`, `rd` or `th`; any other superscript is still unknown markup.
- **Ordinal words.** `verification.ordinal_form` makes ordinal words equal numeric ordinals
  (`Thirtieth` = `30th`, `Twenty-Fourth` = `24th`). It is used in `compare_record` for title,
  journal, booktitle and publisher, and in the proceedings-name variant check.
  - Positive: AltmSchu02's Crossref record "the Twenty-Fourth Annual Conference" matches
    `24\textsuperscript{th}`.
  - Negative controls: `25th`, a wrong suffix (`3th` ≠ `3rd`), and a cardinal (`thirty` ≠ `30th`).
- **Proceedings year only.** `venue_variant_match` also tries the source name with the year removed
  and the acronym kept. CarvEtal22a cites `({comsnets})`.
- **Publisher initials.** `helpers.format_journal_name(..., dotted_initials=True)` writes initials
  undotted and space-separated: `W.H.`, `V.`, `{W}.` and `{T}` become `W H`, `V`, `W` and `T`.
  This reverses stage 2B-i's rule that kept dotted initials.
  - Journal names are unchanged.
  - Book publishers compare with undotted initials (`verification.publisher_initials`).
  - The catalogue same-firm rule now treats a cited initial as distinctive: `J H Freeman` is not
    `W.H. Freeman`. Before this change, single letters were dropped. None of the 33 same-firm
    matches in the baseline changes.
- **Offline check** ([`measure_rules.py`](measure_rules.py), [`measure-code-change.json`](measure-code-change.json)):
  `auto_review.reassess` on all 6,422 saved results with the new code gives the same statuses as
  the old code. The only loss is FranLiu18, the known reassess-only reopen that the pipeline keeps
  through its route validator. There were no errors.

## formats (56 entries)

- **Issue ranges:** `number` `N-M` → `N--M` in 43 entries.
- **Held (11), not form changes:**
  - Eight entries have a page range filed as `number`, with no `pages`: MullEtal05 `866-871`,
    JohnEtal08, WaszWalt83, MullSchu94, Lash50, DelaEtal10, GlovLaw01 and JungEtal08. Each needs a
    source-backed pages correction.
  - vond81 `81-2` is a @techreport number.
  - Alva02 `BCCS-02-01` and Weic96 `1-B` are labels.
- **Proceedings booktitles without the year (5):**
  - CoppEtal17, WangEtal10b and ChenEtal22 drop a leading or embedded year.
  - StonEtal25: "Practice and Experience in Advanced Research Computing: the Power of Collaboration".
  - CarvEtal22a: "14th International Conference on Communication Systems \& Networks ({comsnets})".
    Its ordinal became `14\textsuperscript{th}` in the ordinals batch.
- **Editions:** NoceWrig06 and BorgGroe05 `2` → `2\textsuperscript{nd}`.
- **Publishers (6):**
  - Marr82 and HestEtal05 → `W H Freeman`.
  - MeltMart72 → `V H Winston`.
  - Holl28 → `D Appleton and Company`.
  - Aust14 `{T} Eagerton` → `T Eagerton`. The spelling "Eagerton" is the existing alias-table form;
    the publisher was Thomas Egerton. It is flagged for the user and not changed here.
  - Brow24 → `John Grigg and {William} P Bason`.
- **`@book` pages:** none exist.

## suffix-strip (33 entries)

- 33 author/editor fields: 32 `Jr` and 1 `III` (KahaEtal08a's editor H L Roediger).
  - 23 are in BibTeX's `Family, Jr, Given` form, e.g. `Murdock, Jr, B B` → `B B Murdock`.
  - 10 are bare tokens, e.g. `J Jr Engel` → `J Engel`.
- The plan expected 27; all 33 found by the Jr/Sr/II/III/IV rule are true suffixes.
- Cite keys are unchanged.

## ordinals (34 entries)

- Every plain numeric ordinal in a text field (all except doi, url, pages, volume, number, names,
  address and year) is now `N\textsuperscript{suffix}` with the correct suffix: 23 booktitles,
  6 titles and 5 journal fields.
- No ordinal had a wrong suffix.
- The rule is enforced by [`build.py`](build.py) `propose_ordinals`. Rerunning it on cdl.bib gives
  0 proposals.

## adddoi002 (991 entries)

[`build_adddoi.py`](build_adddoi.py) adds a lowercase bare DOI to every metadata_verified entry
that lacks one, when the DOI is established for the cited, published version:

| Route | Added |
|-|-|
| Crossref-accepted (the missing-DOI advisory): `cited_work_doi` checks: the cited work's own clean record, not a notice or update, the record type fits the entry type, no rival DOI | 336 |
| `verify_entry` approvals saved without `accepted_doi` (the advisory cannot see them): the unique issue-free Crossref candidate, same checks | 540 |
| PubMed/PMC (Europe PMC 65, PMC JATS 12) and publisher-page (3) approvals: the record's DOI, after its Crossref record matched title, first-author surname, year and venue | 80 |
| Cited preprints: the repository DOI (arXiv 30, bioRxiv 5), none naming a published version | 35 |
| **Total** | **991** |

The notice check refines the one in `../apply-2026-09-23/apply.py`. A title word such as
"correction" does not make a record a notice when the cited title contains the same word. Four
articles were affected: Farr14 ("Correcting the correction ..."), JenkEtal02, WallEtal04 and
GothEtal96. SackYang00 on the PubMed route was affected the same way. Update and correction
relations still block. The first-author check reads braced and particle surnames (`{St Jacques}`,
`{van der Meer}`) as surnames. No Crossref fetch was needed, because every DOI's record was
already in the saved evidence.

**Skipped (219), which are the verified entries still without a DOI:**

| Reason | Entries |
|-|-|
| A second DOI also matches title and byline, e.g. APA `//` twins, reissued MIT Press/Elsevier/CUP/OUP books or chapters, OSF/SSRN copies. Needs a per-entry choice. | 126 (all @article) |
| @book verified from the LoC catalogue, where the accepted record has no DOI | 89 |
| Cited preprint with a published version (preprint → published swap list): LeeEtal19, ChieHone19 (10.1016/...), SilvEtal19 (10.1523/...) | 3 |
| Crossref year differs from the cited year (GuggEtal07, PMC route) | 1 |

- Verified entries with a DOI: 3,188 of 4,398 before, 4,179 of 4,398 after.
- Library-wide: 4,199 of 6,422 entries have a DOI. Most needs_review entries still lack one,
  because their identity has to be established first.

## initials (1,142 entries; applied 2026-09-25)

[`names.py`](names.py) (tests: [`test_names.py`](test_names.py), real cdl.bib names) converts
full given names to initials, one per given name.

- Hyphenated given names keep hyphenated initials: `Marc-Oliver` → `M-O`, `Yen-lu` → `Y-L`,
  `Jean‐Philippe` (U+2010) → `J-P`.
- A no-break space counts as a space.
- Surnames, lowercase particles and braced groups are kept as written.
- Every converted name keeps its ID-rule surname (`helpers.last_name`) and passes the house
  formatter, so no key changes.
- PosnEtal87's byline typo `adn` → `and` is fixed in this batch. Crossref
  10.1016/0028-3932(87)90049-2 lists four authors: Posner, Walker, Friedrich and Rafal.
- **Held names at the first build: 204 in 169 entries** (rebuilt counts are under "Applied" below) ([`initials-held.json`](initials-held.json)). Every other name
  in those entries is still converted.
  - **Possible compound or unbraced surname (168).** A full word stands directly before the
    surname, e.g. `C Mejia Arenas`, `Ranxiao Frances Wang`, `A David Redish`,
    `J Kevin O'Regan`, `B A L Di Leone`.
  - **Surname looks like an initial (17).** The name is written family-first, e.g.
    `Miller E K`, `Squire L R`, `Tulving E`. These are byline errors to fix from the source.
  - **Given name the rule does not convert (10).** Examples: `{\L}ukasz`, `{\'{E}}adaoin`,
    `Shui-I`, `M-Marsel`, `A-l`.
  - **Lowercase given token (3).** `a {van Nieuw Amerongen}`, for example.
  - **Braced corporate names rewritten by the formatter (3).**
  - **ID-rule surname would change (2).** `Ting Wu`: `ting` is in the key rule's prefix list.
    `van Zessen` (with a no-break space).
  - **Malformed name (1):** `M \ ' { A } Serrano`.

**Attempt 1 (stopped).** The first cycle ran the PMC metadata layer for 1,149 keys.
`pmc_metadata.check_bulk_hours` refuses bulk PMC requests (more than 100 keys) on weekdays
between 5 AM and 9 PM US Eastern, following NCBI's usage policy.

- The attempt stopped at 09:25 ET.
- cdl.bib was restored byte-for-byte to the suffix-strip state. The attempt's backup, snapshot,
  staging and log are in `.bibcheck/apply-2026-09-27/initials-attempt1-pmc-hours/`.
- When results were read afterwards, `Cache.retain_notices` attached the PMC record fetched during
  the attempt to one needs_review entry (InouEtal15). No status changed.
- [`resync_baseline.py`](resync_baseline.py) re-exported the baseline. The validator gave an exact
  restore, with source_notices 132 and source_article_locators 310.
- Splitting the batch into sub-batches of 100 keys or fewer would avoid the guard without
  following the policy, so it was not done. The batch runs after 9 PM Eastern.

Rebuild the proposals first, because adddoi002 changed the fingerprints of 991 entries:

```
.venv/bin/python verification/apply-2026-09-27/build.py initials
.venv/bin/python verification/apply-2026-09-27/apply.py initials --apply
```

**Applied (2026-09-25, 21:07 ET, Friday; bulk PMC hours).** cdl.bib had changed since the first
build (pilot, merged PRs, replacements, sign-offs, formatter fixes), so the proposals were rebuilt.

- 1,142 entries changed (1,132 author fields, 19 editor fields). Every proposal's fingerprint
  matched the current entry. The staging diff held only author/editor lines, all cite keys were
  unchanged, and `check_bib` passed.
- Seven entries from the first build were dropped because they no longer need a change: Aust14,
  EichMaca06, Hume07, Jame90, MannEtal11 and ZrenEtal11 already have initials, and Mink07 is no
  longer in cdl.bib.
- **Held names: 201 in 166 entries**, down from 204. Two of the dropped names were fixed
  elsewhere: ZhenEtal19's `M \ ' { A } Serrano` is now `M A Serrano` in ZhenEtal20, which replaced it (replace001), and NilsEtal75's `L -G Nilsson` is now `L-G Nilsson`. NilsGard93's `L -G Nilsson` is still held. The
  third, ZrenEtal11's `Karl Ulrich Bartz-Schmidt`, is now `K U Bartz-Schmidt`.
  - possible compound or unbraced surname: 166
  - surname looks like an initial (family-first byline): 17
  - given name the rule does not convert (accented or braced first letter, e.g. `{\'{A}}ine`, `{\L}ukasz`): 10
  - lowercase given token: 3
  - braced corporate name rewritten by the formatter: 3
  - ID-rule surname would change (`Ting Wu`, `van Zessen`): 2
- Accented initials survive the formatter (ca7454a): `reformat_author("M {\'A} Serrano")` and
  `J {\'{A}}lvarez` come back unchanged. The rule does not take an initial from an accented given
  name. Those names are held.
- Production run: 7 requests and 1,434 review writes. The repeat made 0 requests and 0 review
  writes. In the batch, 892 verified entries stayed verified and 19 needs_review entries became
  verified: AxmaEtal08, Bala98a, Bala98b, BalaMacD02, BurgGruz00, Burw00, CahiEtal96, CapaNeat95,
  Faw90, FoucEtal03, Gabr98, McCaEtal89, QuirEtal92, RobbEver07, SharGree94, Sing93, WehnMenz90,
  WelcEtal89 and WienEtal89. No accepted result changed outside the batch. The library went from
  4,476 / 1,974 to 4,495 / 1,955 metadata_verified / needs_review (31 human_verified, 6,481 entries).
- The cdl.bib edit, the proposals and the run-cycle results were committed as a4e03de at 21:28 ET,
  during the repeat cycle. The repeat-stage results, baseline, review queue, restore record and
  validator update were committed after the checks passed.
- `.bibcheck/validate-current-checkpoint.py` now also accepts the initials staging file as the last
  applied batch. `verification/apply-2026-09-29/library-changes.json` still names replace001 as
  `last_staged`.

## verify/commit gate (user, 2026-09-26)

`bibcheck.py check_library` is the gate shared by `bibcheck.py verify` and `bibcheck.py commit`.
It runs three steps:

1. The format check.
2. `crossref verify --auto-review` on the entries that are new or edited relative to the GitHub
   master cdl.bib, the file `compare_bibs` uses. Key-only renames are excluded.
3. An offline library-wide status line.

`verify` exits 1 on a format error or any unresolved changed entry. It prints each such entry's
key, its issues, and the closest source's field issues, and points to `crossref review-packet` and
`crossref approve`. The library-wide backlog is reported but does not fail `verify`.

- `--no-citations` gives an offline, format-only check.
- `--all` verifies every entry.
- `--reference`, `--database` and `--mailto` (or `CROSSREF_MAILTO`) are also accepted.

`commit` refuses (exit 1) on the same conditions. When the gate passes, it commits only the
bibliography file with `subprocess.run(['git', 'commit', '-m', msg, '--', file])`, with no shell
and no `-a`.

The tests are in section 16 of `tests/test_machinery_2026_09_25.py`. They use real entries (Rame72
and Zoll90) and real Crossref requests into a fresh cache, with no mocks:

- A correct changed entry passes.
- A wrong volume fails and shows `volume: missing evidence or mismatch`.
- `--no-citations` stays offline.
- `--all` checks unchanged entries too.
- `commit` refuses an unresolved entry, then commits only cdl.bib while another modified file
  stays uncommitted.

README.md's workflow section describes the gate.

## Checks after each batch

The following passed after every committed batch:

- `.bibcheck/validate-current-checkpoint.py`: exact restore of 6,422 entries, 0 repeat imports,
  SQLite ok.
- `verification/benchmark/run.py`: 60/60, with 0 false acceptances and 0 missed matches.
- `bibcheck.py verify --no-citations`: "looks good!".
- Full pytest, including `test_names.py`.
