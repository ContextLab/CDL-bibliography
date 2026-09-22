# Local continuation: source corrections and dotted initials

The local baseline is now **2,257 metadata_verified / 4,165 needs_review** across
6,422 entries, up **51** approvals from the preceding pass. There are no pending
entries or provider errors. Nothing was committed or pushed; no LLM was called.

## Changes and observed results

- Corrected **GonzEtal19**, **PeirEtal19**, and **WallEtal04** from article sources.
  All three subsequently passed deterministic verification. The title, ordered
  author initials, DOI, year, volume, and pagination match the separately recorded
  source observations: **18/18 comparisons**. See [the source audit](source-audit.md)
  and [before/after corrections](corrections.json).
- Fixed author tokenization for explicitly dotted initials: `A.A.` and `A A`,
  `M.E. J.` and `M E J`, and `Michael G.H` and `Michael G H`. Undotted acronyms,
  missing initials, conflicting full names, suffixes, and author order retain
  their existing rejection boundaries. Resolver revision **4** reconsiders only
  unresolved cached evidence. Existing accepted entries remain untouched.
- The initial dry run proposed 49 approvals from this formatting repair.
  Inspection found a separate Sammon suffix conflict; its existing
  external-evidence hold prevents approval. **48** entries cleared offline.
- Resolver changes can also make an existing candidate DOI newly eligible for
  secondary lookup. That transition now reopens the checkpoint while retaining
  previously checked DOIs. A regression runs the new DOI lookup once, retains
  the unresolved title mismatch, and makes no lookup on the repeat. An audit
  of actual completed secondary lookups found no unqueried eligible DOI hidden
  behind a completion flag in the resulting library.

## Expanded discovery experiment

The frozen [100-entry manifest](manifest.json) contains 25 entries from each
existing queue route, selected by a deterministic hash ordering. None had a
completed expanded-title search or attached research evidence. This is a
stratified diagnostic batch, not an estimate of population accuracy.

The pipeline completed all 100 expanded title queries, secondary metadata,
article-front-matter and publisher-year stages. The successful network run used
**104 requests**: three corrected-entry registry requests, 100 title searches,
and one four-DOI secondary batch. It cleared the three corrected entries but
**none of the 100 directly**. Its repeat used **zero requests and zero new review
records**. The initial sandbox attempt failed DNS resolution; the authorized
network-enabled retry resumed from the cache.

Two of the 100, **TurGEtal17** and **ColeEtal01**, later cleared through the
offline initials fix. The first discovery outcomes are preserved in
`discovery-initial-results.json`; current counts are in `summary.json`.

| Set | Verified | Still unresolved |
| --- | ---: | ---: |
| Original 50 | 39 | 11 |
| Wider 50 | 11 | 39 |
| Next 100 | 2 | 98 |
| Entire bibliography | 2,257 | 4,165 |

The original blind 50-source extraction audit is unchanged. Its extraction
agreement is distinct from the citation approval counts above.

## Validation

- **273 tests passed**, including 23 new dotted-initial and checkpoint cases.
  There were 7,954 existing bibtexparser/pyparsing deprecation warnings.
- **60/60 documentary benchmark cases** passed: no false acceptances or missed
  matches within that bounded benchmark.
- The bibliography formatting/duplicate validator and `git diff --check` passed.
- All **2,206 previously accepted snapshot records are exactly unchanged**,
  including evidence and check times.
- Initial offline reassessment added 4,213 review records once. Its repeat added
  **zero**; a subsequent invocation also added zero in both cycles. These runs
  have no network client. The original timings remain in
  `offline-initial-stages.json`.
- The complete new snapshot restored into a fresh SQLite database with all
  6,422 statuses, fingerprints, check times, and external-evidence holds intact.
  SQLite integrity checking passed. See `artifact-checks.json`.
- An initial report-export bug assumed every older direct-verification result
  had an `accepted_doi` label. The report now obtains the unique supported DOI
  from its documentary candidates when that label is absent. The baseline
  export itself was intact; rerunning the report made no verification writes.

Snapshot SHA-256:
`a68366948848ae52564860214daeb84152f7b0e782e253564ea4401e48809923`.

## Reproduce locally

From the repository root:

```sh
.venv/bin/python verification/resolution-followup-2026-09-15/run.py
.venv/bin/python verification/resolution-followup-2026-09-15/reassess.py
.venv/bin/python verification/resolution-followup-2026-09-15/check_artifacts.py
.venv/bin/python -m pytest -q tests
.venv/bin/python verification/benchmark/run.py
.venv/bin/python bibcheck/test.py
```

`run.py` keeps the same frozen batch on subsequent invocations. Source response
bodies, the working SQLite database, full reports, and logs remain ignored under
`.bibcheck/resolution-followup-2026-09-15/` or the sibling follow-up log files.

## What remains

The 100-query result gives little support for indiscriminately widening title
searches. Further resolution should target the actual blocker: original
bylines and author corrections, publication types, book/chapter editions, and
historical issue or imprint evidence. The remaining original-pilot erratum,
publisher, date, and locator cases remain unresolved. No ownership-based
publisher aliases or LLM approvals were added.

The current queue routes are 1,937 source-discovery cases, 1,013 author-identity
cases, 957 field-adjudication cases, and 258 publication/version cases. These
routes guide the next source collection; they are not permission to accept a
near match.
