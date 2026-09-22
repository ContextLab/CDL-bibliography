# Incremental citation verification — September 14, 2026

The cache and automatic change-checking workflow now implement the requested
contract: new and edited entry content is checked; unchanged verified content
and key-only renames reuse prior decisions. The one-time baseline covers all
6,422 entries. It does **not** establish that all 6,422 are correct: 1,852 have
supported metadata matches and 4,570 remain unresolved.

## Assessment of the approach

Retain deterministic source comparisons, a persistent response cache, and a
content-addressed decision cache. This makes repeated checks inexpensive and
keeps uncertainty visible. It also follows Crossref's recommendation to
[cache results and avoid repeated requests](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).

The evidence does not support scaling the existing generic search/PDF/LLM
experiments as a universal automatic verifier. The earlier ten-query expanded
Crossref pilot resolved zero entries; literal PDF quotations do not establish
metadata roles or publication identity. The current library has only 69 entries
with explicit DOIs, so most initial checks depend on discovery. Of the unresolved
entries, 3,972 are articles, all 193 books remain unresolved, and 85 of 86
`inproceedings` entries remain unresolved. These are coverage findings, not error
counts.

The next coverage work should add narrowly tested structured-source adapters
for identifiable publication families. The documented NeurIPS publisher record
is one concrete example of evidence the earlier registry search could not
establish. Independent fixtures must cover matching records, wrong authors,
wrong dates/pages, unrelated works, and preprint/final-version confusion before
an adapter may grant approval. This change deliberately preserves the existing
comparison policy; it does not relabel the backlog as verified.

## Implemented

- Fingerprint format v2 excludes only the citation-key token. All other raw
  entry content and shared/inherited dependencies remain significant.
- Indexed lookup works across key renames. The latest decision wins across
  keys; concurrent migration cannot supersede a newer decision.
- Exact legacy matches migrate without source requests, changed check times,
  or changed evidence. Schema-2 snapshots restore across clone paths and key
  renames. Old schema-1 snapshots remain importable for exact legacy matches.
- Fixed the pre-existing snapshot rejection of valid Europe PMC/PMC approvals.
- `verify` supports `--against BASE.bib` or `--keys FILE`. All free layers
  respect selection. `status` also supports `--against`. Full reports retain
  the backlog, while the exit code gates selected entries.
- Current approvals are not reassessed by ordinary automatic review. Explicit
  refresh/reassessment and comparison-policy changes remain available.
- Added an Actions workflow for PRs, pushes, and manual full-library runs,
  with resumable SQLite storage and portable failure checkpoints.

## Observed validation

- 186 tests passed, including migration races, key renames, non-key edits,
  dependency changes, source failures, selection, and snapshot restoration.
- Frozen benchmark: 60/60 cases passed across 30 works. This remains a
  regression benchmark, not a population accuracy estimate.
- Full bibliography formatting and duplicate checks passed.
- Ruff, actionlint, and diff whitespace checks passed.
- Compared every migrated baseline record with the committed original:
  all 6,422 retained exactly the same evidence, policy, status, and check time.
  Updated the 4,570 review-queue fingerprints without changing its decisions.
- Full ordinary verification plus free review layers: 6,422 cached results,
  1,852 verified / 4,570 unresolved, **zero network requests**.
- Local execution of the actual PR CI driver against the unchanged base:
  exit 0, zero selected entries, zero network requests. Hosted execution is
  not yet proven.
- Timing probe on this machine: full parse/fingerprints 6.21 seconds; indexed
  review retrieval for 6,422 entries 3.39 seconds. Report serialization,
  snapshots, and repeated validation reads add further time.

The isolated live `verification/incremental_pilot.py` checked `Rame72` against
Crossref, then ran the same citation unchanged, renamed its key, and changed
its year to 1900:

| Stage | Result | Network requests |
| --- | --- | ---: |
| Initial live DOI lookup | metadata_verified | 1 |
| Unchanged content | metadata_verified, same check time | 0 |
| Key-only rename | metadata_verified, same check time | 0 |
| Incorrect year | needs_review, new fingerprint and check time | 0 |

The last stage recomputed the comparison using the cached source response.
It did not reuse the old approval. Private diagnostics are under
`.bibcheck/incremental-tinhhcyb/`. An earlier sandbox DNS failure was recorded
as a provider error; the successful live run used approved network access.
Neither run edited `cdl.bib` or changed its production review decisions.

## Deployment boundary

Changes are local. Publish the workflow and set the Actions repository variable
`CROSSREF_MAILTO` to activate live checks; configure the `citations` check as
required if failed verification must block merges. No push, merge, branch-rule
change, or GitHub configuration change was performed here.

SQLite is durable locally. GitHub caches and artifacts can expire, so retain
new review decisions in periodic committed/downloaded snapshots. Cache eviction
can require repeating decisions that were never added to a durable snapshot.
Unresolved legacy records remain available for targeted correction or improved
source coverage, and provider failures remain retryable.
