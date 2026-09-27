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
