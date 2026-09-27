# Final apply (2026-09-30-final folder, run 2026-09-27): resolution batches 27-39 and the held forms

This folder applies the last pending changes to cdl.bib, one batch and one commit each:

- `res27`: `../resolution-2026-09-26/batch-27.json` (the 21 spot-check entries never queued);
- `res28to33`: batches 28-33 of the evidence-completion queue (`../resolution-2026-09-27/queue.json`);
- `res34to39`: batches 34-39, plus the fields `helpers.check_bib` rejected in waves 2-9 for entries no batch
  row names (HeniEtal19, Calk96, RangEtal14, BartEtal04c, Youn12).

The rows are not wave rows (`"wave": null`), so [`build.py`](build.py) builds the proposals directly from each
row against the current cdl.bib entry (after the batches before it):

- `apply`: every `set` value is checked with `postcheck.resolution_quote` (`../research-2026-09-25/postcheck.py`:
  each quote found at its URL, the value's words in the quotes, the user's inference rules). A value that fails is
  applied only when the row's notes say it was read in a browser or transcribed from a scan
  (`postcheck.BROWSER_OR_SCAN`), with a `resolution_quote_unverified` flag in the proposals file; any other failure
  is listed under `set_not_applied` and the field is left unchanged. The value is put in house form with the
  post-check's normalisers (names with `normalise_names` and `house_surname`, em dash `a---b`, issue ranges, pages,
  proceedings booktitles, editions, US addresses, unprinted countries dropped, DOI case, guarded title, journal and
  publisher formatter forms, ordinals). `remove` drops fields and `entrytype` sets the type. `withdraw` names
  research proposals of the waves and changes nothing here.
- `drop`: the entry is deleted (never KahaEtal08b or JacoEtal05b; an absent or already deleted key is a no-op).
- `keep`: nothing.
- Keys: after the batch every key must equal `helpers.authors2key` of its author (or editor) and year, with the
  suffix rule. An entry whose key base moves takes the new base; when that base is taken, the existing entries keep
  their order and the first suffixes, and the moved entry takes the next one (Buzs01 -> Buzs02b, the existing
  Buzs02 -> Buzs02a; resolution-plan README default). Every row's `new_key` agreed with this plan.
- Every key was found in cdl.bib as written (no row needed `../key-renames.json` to be followed).

The runner is [`apply.py`](apply.py), the waves 2-9 runner pointed at this folder (frozen proposals with
fingerprints, a staging diff limited to the batch, `helpers.check_bib`, backup and snapshot under
`.bibcheck/apply-2026-09-30-final/`, the production pipeline for the batch keys, a repeat with 0 requests and 0
review writes, no change to any accepted result outside the batch, the baseline and review-queue exports).
[`log.py`](log.py) logs renames and deletions and writes `library-changes.json`, whose `steps`
`.bibcheck/validate-current-checkpoint.py` now applies after the waves 2-9 steps (the previous validator is kept as
`.bibcheck/apply-2026-09-30-final/validate-current-checkpoint.py.bak`). Each batch was committed in a scratch
worktree at HEAD first, where the full pytest suite and `verification/benchmark/run.py` had to pass.

## Special cases

- ElliAshb88 is kept: batch 30 drops it, batch 18 (reconciled) keeps it, and the resolution-plan README's "NOTE for
  final apply" says batch 18 wins.
- HeniEtal19 gets pages `ENEURO.0306-19.2019` (`../resolution-2026-09-27/NOTICES.md`: "pages missing;
  Crossref=PubMed=PMC give ENEURO.0306-19.2019, so add it").
- The 15 fields check_bib rejected in waves 2-9 (`../apply-2026-09-29-waves2-9/README.md`, "Fields check_bib
  rejects"), with the formatter of 9f84506:
  - applied from the batch rows here (the later row, written against the current entry, decides the value):
    KingEtal11 author `M J Morrell and {RNS System in Epilepsy Study Group}` (and with it the key MorrRNSS11),
    BrinCrag72 `28P--29P`, Fish22's full journal title, Unde45 `i--33`, Ward37 `i--64`, Webb17 `i--90`,
    ViveEtal10 `24ra22`, MullSchu94 `81--190, 257--339`; Perr14 takes batch 35's `1--97` (catalogue extent
    `97 p.`) over the wave's `i--97` (conflict, the later row wins);
  - applied from the wave's final change: HeniEtal19 pages `ENEURO.0306-19.2019`, Calk96 `i--56`, BartEtal04c
    `La Jolla, {CA}`, and in the braced form the formatter now keeps: HeniEtal19 journal `{eNeuro}`, RangEtal14
    publisher `{PMLR}`;
  - still rejected: Youn12's `url` (not a house field; `bibcheck/keep_fields.txt`).

## Exceptions check_bib forces (build.py)

- `HOUSE_FORM`: BaayEtal95 title `{CELEX2}` -> `{C}{ELEX2}` (the formatter strips a fully braced title, as
  `{B}{ASIC}` in wave 8); HeniEtal19 `{eNeuro}`, RangEtal14 `{PMLR}` (above). AzizEtal91's title keeps the cited
  `{Parkinsonism}` (the formatter's form is the value as cited: no change).
- `HOLD_CHANGE`: FoodAdmi20a and FoodAdmi20b keep `Force`. Removing it exposes the group author
  `{U.S. Food and Drug Administration}`, which the author formatter still splits at ` and `
  (`{ U S Food and Drug Administration}`); `{U.S. Food {and} Drug Administration}` survives the formatter but
  changes the key base. Their howpublished values already equal the rows' values.

## Conflicts between rows

Every one is listed under `conflicts` in the proposals files:

- ElliAshb88: batch 18 apply vs batch 30 drop -> kept (README NOTE for final apply).
- Decision changes where an earlier batch said `keep` and a batch here says `apply` (the later row wins):
  Beaz96 (25), Bull90 (07), BunnEtal99 (10), Kroh35 (14), Puff79 (21), Tulv68 (22), Tulv72 (21), Youn68 (22),
  ZackHash94 (20).
- Perr14 pages: wave 6 `i--97` vs batch 35 `1--97` -> batch 35.
- No field is set to different values by an earlier resolution batch and a batch here, and no batch-27 key has a
  wave row.

## Open questions in the rows

The rows of BaayEtal95, BrinCrag72, Bull90, Frie79, IzauBoni01, RaaiShif81b, RescWagn72, Unde45, ViveEtal10, Ward37
and Webb17 carry `questions` for the user. Their decisions were applied as written; the questions are copied into
the proposals files (`questions`).

## Results

Library counts come from `bibcheck.py crossref status cdl.bib`.

| Batch | Proposals | Requests (run / repeat) | Review writes (run / repeat) | Seconds (run / repeat) | Library after |
|-|-|-|-|-|-|
| start | | | | | 6,390 entries: 6,023 verified, 336 needs_review, 31 human |
| res27 | 21: 21 edited, 3 renamed, 0 deleted | 25 / 0 | 70 / 0 | 731 / 671 | 6,390 entries: 6,042 verified, 317 needs_review, 31 human |
| res28to33 | 26: 24 edited, 5 renamed (1 rename only), 1 deleted (EngeEtal93) | 10 / 0 | 107 / 0 | 710 / 675 | 6,389 entries: 6,046 verified, 312 needs_review, 31 human |
| res34to39 | 24: 23 edited, 0 renamed, 1 deleted (Rayp68) | 6 / 0 | 80 / 0 | 705 / 669 | 6,388 entries: 6,052 verified, 305 needs_review, 31 human |

In res34to39, BartEtal04c, Calk96 and RangEtal14 (batch keys) went from verified to needs_review: the address,
pages and publisher added from the waves are not in the record that verified them. Most rows of batches 28-39 set
values the entries already hold; those entries wait for the research route (`bibcheck/research_route.py`,
3a4532f), which is not part of this pipeline.

## Mop-up batch (`mopup/`, run 2026-09-27 after the research route's final run)

`mopup/build.py` runs this folder's `build.py` rules on the research route's mop-up resolution batch
(`../research-route-2026-09-27/batch-40.json`, read as batch 40; `OVERRIDE` is not applied, since batch 40 keeps
ElliAshb88 too). `mopup/apply.py` is this folder's runner pointed at `mopup/` (work files under
`.bibcheck/mopup-2026-09-27/`). There are 2 edits: ElliAshb88 `Address` `Toronto, Canada` -> `Toronto` (LoC
87026602 prints no country) and Mann06 `Type` `Senior honors thesis` -> `Senior thesis` (as the author's
publication list prints it). There were no renames or deletions, so `library-changes.json` is unchanged. The run
made 0 requests and 6 review writes, and its repeat made 0 requests and 0 review writes. No accepted result
outside the batch changed (`mopup/mopup-results.json`). `.bibcheck/validate-current-checkpoint.py` now applies
the frozen mop-up proposals on top of the organization-keys state, and requires the result to equal the mop-up
staged file and cdl.bib.
