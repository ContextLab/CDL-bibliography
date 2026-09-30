# Research route: final run (2026-09-27)

This run follows the notice-accounting hook in `Cache.retain_notices` (README, "Cache.retain_notices: the
notice-accounting hook") and the organization-author formatter fix. The five renamed entries were
reviewed by the production pipeline before the route ran (`review_renamed.py`, `review-renamed.json`).
The pipeline made 0 network requests, and its repeat added 0 review records.

## After the user answers of 2026-09-28 (decisions0928): 1 approved, 3 re-approved, 1 left

The decisions0928 batch (`../apply-2026-09-27b-final/decisions0928/`, commit 4071cf3) changed R12's author and
renamed R12 -> RCor12, MorrRNS11 -> MorrRNSS11, US20a/b -> USFo20a/b, GrilEtal06a -> GrilEtal06, and dropped
GrilEtal06b. `bibcheck.py crossref status cdl.bib`:

- before: 6387 entries: human_verified=31, metadata_verified=6354, needs_review=2
- after: 6387 entries: human_verified=31, metadata_verified=6355, needs_review=1

| Run | Approved | Re-approved | Not approved | Review writes |
|-|-|-|-|-|
| dry run (`dry-run-5.json`) | 1 | 3 | 1 | 0 |
| backfill (`backfill-5.json`) | 1 | 3 | 1 | 4 |
| repeat (`repeat-5.json`) | | | 1 | 0 |

RCor12 is the approval (its author `{R Core Team}` matches the wave-9 row's evidence). The re-approvals are
MorrRNSS11, USFo20a and USFo20b (renamed). SvenEtal24 is still not approved: its author was never researched,
and no official record spells out 'NT' (resolution-plan README, "User answers 2026-09-28").

## Mop-up of the 38 (2026-09-27, later): 37 approved, 1 left

`bibcheck.py crossref status cdl.bib`:

- before: 6388 entries: human_verified=31, metadata_verified=6319, needs_review=38
- after: 6388 entries: human_verified=31, metadata_verified=6356, needs_review=1

| Run | Approved | Not approved | Review writes |
|-|-|-|-|
| dry run (`dry-run-4.json`) | 37 | 1 | 0 |
| backfill (`backfill-4.json`) | 37 | 1 | 37 |
| repeat (`repeat-4.json`) | | 1 | 0 |

No evidence file was left out as uncommitted, and no earlier approval was re-approved or withdrawn. What
cleared each group:

- Notices with no DOI (11): classification rows now name the exact DOI-linked records they were made beside
  (record identity, `README.md` "Notices with no DOI: record identity"; `Cache.retain_notices` keeps the
  approval, and any other or changed record reopens it).
- Unclassified DOI-linked records (12) and PurcEtal10, Buzs02b, LeVaEtal08, PfurEtal96, Este91: classified
  (`../resolution-2026-09-27/NOTICES.md`, "Mop-up classification"). No retraction or expression of concern.
  Unread (approved with `notice_unread`, listed for the user): JohnEtal98, PurcEtal10's third link, ChanEtal12.
- ElliAshb88: batch 30's row is now `keep` (batch 18 wins). Its author and title are quoted from PMC reference
  lists under the RaaiShif81b default, and its address became `Toronto`, since LoC prints no country (mop-up batch
  `batch-40.json`).
- Frie12, Frie08: the route took batch 30's `Frie08` row (Friendly) through the rename log to Frie12 (Friedman).
  Batches 27 on now follow only renames logged after their commit. Batch 30's editors were not applied to Frie12,
  because they are Friendly's book's editors.
- Mann06: its Type is now `Senior thesis`, as the author's publication list prints it. The manual research's
  composite quote was in no saved body (`batch-40.json`).
- Post-check `needs_user` residue (5): each has a later resolution `apply`, and the residue is of a settled kind
  (`README.md` "Post-check residue a resolution settles"). ChanEtal12 and LegaEtal11 had merged duplicates, and
  DougPeuc73 and Kolo13 had `field_not_found`. McCaEtal06 had the DOI residue, which the DOI default settles.
  ChanEtal12 then showed an unclassified corrigendum, which is now classified as unread.

cdl.bib edits (mop-up apply, `../apply-2026-09-27b-final/mopup/`): ElliAshb88 address and Mann06 type. There were
no renames or deletions. The run made 0 requests, and its repeat made 0 requests and 0 review writes.

### The 1 entry still needs_review

- SvenEtal24: the author was never researched. The open 'Hoang NT' question is left for the user.

### For the user

- ChanEtal12: the Brain Res 1470:159 corrigendum is unread. Its Crossref title quotes the article as "A
  meta-analytic review", but the article and the entry print "a meta-analysis".

## Counts (first final run, before the mop-up)

`bibcheck.py crossref status cdl.bib`:

- before: 6388 entries: human_verified=31, metadata_verified=6052, needs_review=305
- after: 6388 entries: human_verified=31, metadata_verified=6319, needs_review=38

| Run | Approved | Re-approved | Held by a notice | Not approved | Withdrawn | Unchanged | Review writes |
|-|-|-|-|-|-|-|-|
| dry run (`dry-run-3.json`) | 268 | 2 | 28 | 9 | 1 | | 0 |
| backfill (`backfill-3.json`) | 268 | 2 | 28 | 9 | 1 | | 299 |
| repeat (`repeat-3.json`) | | | | 10 | | 28 | 0 |

- The 268 approvals include AfraEtal06 and the other entries that `retain_notices` used to reopen. They
  also include US20a, US20b and MorrRNS11.
- The two re-approvals are Cent23 and R12. They were renamed, so their checked fields changed.
- The withdrawal is Frie12. Batch 30 sets an editor value that cdl.bib does not carry yet.

`verification/baseline.jsonl.gz` and `verification/review-queue.jsonl.gz` were exported by `export.py`,
and the review queue holds 38 entries. The fresh restore (`.bibcheck/validate-current-checkpoint.py`)
restored 6388 entries with identical statuses, 0 repeat imports and sqlite ok
(`../completion-2026-09-15/restore-latest.json`).

## The 38 entries still needs_review

### The route approves them, but `retain_notices` still reopens them (16)

The hook keeps an approval only for notices it can name by notice DOI. It also requires every record of
the cited DOI to be covered.

Notice classified, but the classification has no notice DOI (11):

- BisbBurg14: metadata correction (issue repaginated), with no registered notice DOI.
- ParkEtal08: content-only erratum, with no registered notice DOI.
- HubeEtal01: unread old erratum, no notice DOI.
- KahaEtal06: unread old erratum, no notice DOI.
- KossEtal99: unread old erratum, no notice DOI.
- MarsEtal00: unread old erratum, no notice DOI.
- VargEtal97: unread old erratum, no notice DOI.
- Fred04: coordinate conflict (PubMed 1367-1378 against Crossref 1367-1377). The entry already carries
  Crossref's value. Held by an article-locator record.
- FrieEtal99: classified no_notice. Held by a PubMed author-suffix record.
- McDoEtal10: classified no_notice ('Hagler DJ Jr'). Held by a PubMed author-suffix record.
- Murd56: classified no_notice. Held by a PubMed author-suffix record.

Other reasons (5):

- Este91: the entry has no DOI. The suffix record belongs to an unrelated candidate's DOI (classified
  unrelated).
- PurcEtal10: its Europe PMC record lists 3 "Erratum in" links, but only 2 notices are classified. The
  third link has not been read.
- Buzs02b: no DOI, and the notice record comes from a candidate DOI in its history. It is not classified.
- LeVaEtal08: a PubMed author-suffix record on the cited DOI, not classified.
- PfurEtal96: a PubMed author-suffix record on the cited DOI, not classified.

### Held: DOI-linked evidence with no classification (12)

These are not in `notices-classified.json`, so the route itself holds them:

- BarrEtal18: Crossref registry notice, plus an article-locator record.
- JohnEtal98: notice record plus an author-suffix record.
- MankEtal12, MarkEtal95a, MonaAbbo11, RebeEtal02, RutiEtal08, SohnEtal00, StarDava06, WangBuzs96,
  WheeEtal00: a DOI-linked notice record.
- VirtEtal20: a DOI-linked notice record.

### Not approved by the route (10)

Post-check `needs_user` residue (5):

- ChanEtal12 (wave 2)
- DougPeuc73 (wave 1)
- Kolo13 (wave 1; also has pending removals)
- LegaEtal11 (wave 7)
- McCaEtal06 (wave 7)

Other reasons:

- ElliAshb88: batch 18 keeps it and batch 30 drops it, so the resolution decisions conflict.
- Frie08: the editor words 'chen' and 'hardle' are not in the quotes, and the volume was never researched.
- Frie12: batch 30's editor value is not yet in cdl.bib (withdrawn in this run).
- Mann06: the `type` quote is not found in its saved body.
- SvenEtal24: the author was never researched (the open 'Hoang NT' question).
