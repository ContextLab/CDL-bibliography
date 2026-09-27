# Stage 3 (2026-09-29-waves2-9 folder, run 2026-09-26): research waves 2-9

This folder applies the post-checked research of waves 2 to 9
(`../research-2026-09-25/wave{2..9}/merged.json`, which already carries the user's cross-wave decisions and
the resolution batches in `../resolution-2026-09-26/`), one batch and one commit per wave:

- every **ready** row (`needs_user` false, no `remove_entry`) gets its final changes: the `final_changes`
  values, the field `removals`, the entry type and the key plan (`rename`, or `collision` with the existing
  entry's `also_rename`);
- every row with `remove_entry` is deleted, unless the post-check marked the drop a no-op (the entry is already
  absent, or its key is a reused key listed in `../key-deletions.json`). KahaEtal08b and JacoEtal05b are never
  deleted: they now name other works;
- every row with `needs_user` true is left exactly as in HEAD. Those entries are held for the user (their
  evidence is being strengthened) and will be applied later.

The merged files were frozen at the start (2026-09-26 22:29 ET) under
`.bibcheck/apply-2026-09-29-waves2-9/inputs/`, and each proposals file records the sha256 of its input.

## Why one commit per wave

The pipeline cost grows with the number of batch keys, not with the number of batches. The wave-1 batch (158
kept keys) took 1,134 s and its zero-request repeat 782 s, so one batch of all eight waves would cost about
as much as eight batches. Per-wave batches keep each commit reviewable and let a failure stop at one wave. The
waves are applied in order: each wave's proposals are built against cdl.bib after the waves before it, and a
row's key is followed through the earlier batches' renames.

## Discipline

The runner is [`apply.py`](apply.py). It reuses `../apply-2026-09-28-wave1/apply.py` (the stage that allows a
new key to be a key the same batch removes) on `../apply-2026-09-29/apply.py` and `../apply-2026-09-28/apply.py`,
pointed at this folder:

1. The proposals are frozen with entry fingerprints (`<wave>-proposals.json`, built by [`build.py`](build.py)).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-29-waves2-9/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0 review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. [`log.py`](log.py) logs the renames in `../key-renames.json` and the removals in `../key-deletions.json`
   (reason and decision source: the resolution batch and its notes, from `merged.json`), and writes
   [`library-changes.json`](library-changes.json).
8. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore
   (`../completion-2026-09-15/restore-latest.json`). It now reads this folder's `library-changes.json`. The
   renames of these batches chain (wave 1: Frie08 -> Frie08a and Frie06 -> Frie08b; wave 8: Frie08a -> Frie12 and
   Frie08b -> Frie08), so one flat old -> new map no longer describes the library. The validator applies the
   earlier flat map and then this folder's batches as ordered `steps` (removals, then simultaneous renames). The
   previous validator is kept as `.bibcheck/apply-2026-09-29-waves2-9/validate-current-checkpoint.py.bak`.
9. The committed state is proven first: a scratch worktree at HEAD gets the batch's files and a commit, and the
   full pytest suite and `verification/benchmark/run.py` must pass there. Only then is the batch committed here.
   The suite's gate tests take the Crossref contact from `CROSSREF_MAILTO`, set from the main cache (the
   worktree has no `.bibcheck/`).

## Five pending entries verified with wave 2

Commits e920c54 and ce6c315 (after the wave-1 run) edited Galt83, BancEtal65, Yate66, Wech45 and Mann06 without
running the pipeline, so they were `pending` at the start and the fresh restore could not import them (6,395 of
6,400). They are the wave-2 batch's `verify_keys` (unchanged entries the pipeline verifies with the batch; added to
`wave2-proposals.json` after a first wave-2 run, which was then redone from the backup).

## Exceptions that `check_bib` forces (in build.py)

- `HOUSE_FORM`: the formatter's fixed point for an approved value, when it only changes the form: braced
  `{American}`, `{University}`, `{MIT}`, `{Georg}`; lowercased braced acronyms such as `({eurospeech})`,
  `({mobisys})`, `{ieee/acm}` (the wave-1 precedent, Kipp01); `{A}` after a colon in a booktitle; a braced capital
  after opening quotes (`` ``{G}eneral ``); `(1993{a})`; `$1/{f}^2$`; `Chat{GPT}` and `{B}{ASIC}` for titles
  whose full braces the formatter strips; the software title `{naturalistic-data-analysis}/...`; and names
  with a dot accent or a Polish L in Unicode (the formatter strips `\.` and garbles `{\L}`; cdl.bib already
  prints names in Unicode). Where the fixed point is the value as cited (Laks01's booktitle, RCor12's author,
  SzpuTulv11's booktitle), the change is not made.
- `HELD`: approved values that `check_bib` cannot accept in any form tried. They stay as cited:
  - pages it cannot parse: HeniEtal19 `ENEURO.0306-19.2019`, BrinCrag72 `28P--29P`, ViveEtal10 `24ra22`,
    and the roman-to-arabic ranges of Perr14, Unde45, Ward37, Webb17 and Calk96 (`i--97` and the like);
  - HeniEtal19's journal (`eNeuro` becomes `Eneuro`), Fish22's journal (`of a Mathematical` becomes
    `of {A} Mathematical`), RangEtal14's publisher (`PMLR` becomes `Pmlr`), BartEtal04c's address (`La Jolla`
    becomes `{LA} Jolla`);
  - Youn12's `url` (not a house field; its volume, number and pages are still removed);
  - KingEtal11's author list (`{RNS System in Epilepsy Study Group}` becomes `{ R N S System ...}`, as with the
    wave-1 FoodAdmi20a case), and with it the rename to MorrRNSS11 that follows the new author. Its title fix is
    applied.
- `DEFERRED_RENAMES`: Shim95 -> Shim95a is applied in wave 8 with Shim94 -> Shim95b (one cross-wave decision; a
  lone Shim95a fails the suffix rule in wave 2).
- `SUFFIX_RENAMES`: the suffix rule after a wave's renames: ChanEtal12b -> ChanEtal12, MairEtal09a -> MairEtal09
  (wave 2), LegaEtal11a -> LegaEtal11 (wave 3), CoheEtal08b -> CoheEtal08 (wave 4), Arch11a -> Arch11 (wave 6),
  Frie08b -> Frie08 (wave 8, as the wave-1 README expected) and deCa05b -> deCa05 (wave 9).

## Results

Library counts come from `bibcheck.py crossref status cdl.bib`.

| Wave | Proposals | Held rows | Requests (run / repeat) | Review writes (run / repeat) | Seconds (run / repeat) | Library after |
|-|-|-|-|-|-|-|
| start | | | | | | 6,401 entries: 4,537 verified, 1,828 needs_review, 5 pending, 31 human |
| wave2 | 191: 189 edited, 19 renamed (1 rename only), 1 deleted (CronEtal94); 5 pending entries verified with it | 8 | 5 / 0 (first attempt 220) | 22 / 0 (first attempt 702) | 809 / 773 | 6,400 entries: 4,590 verified, 1,779 needs_review, 31 human |
