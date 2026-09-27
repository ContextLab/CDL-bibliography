# Research route: final run (2026-09-27)

This run follows the notice-accounting hook in `Cache.retain_notices` (README, "Cache.retain_notices: the
notice-accounting hook") and the organization-author formatter fix. The five renamed entries were
reviewed by the production pipeline before the route ran (`review_renamed.py`, `review-renamed.json`).
The pipeline made 0 network requests, and its repeat added 0 review records.

## Counts

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
