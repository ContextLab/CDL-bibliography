# New metadata sources for the Phase-0 leftovers (2026-09-23/24)

Targets: the 477 `article-no-record` entries and the 460 `individual` entries
in [../phase0-2026-09-22/groups.json](../phase0-2026-09-22/groups.json), 937
entries in total. `cdl.bib` and `.bibcheck/verification.sqlite3` were not
modified. The main cache was opened read-only (`mode=ro`). Responses are
cached in `.bibcheck/extra-sources.sqlite3`. All bibcheck modules except the
new `bibcheck/extra_sources.py` were loaded from the committed HEAD
(79922d4 for the final full run). No keys changed fingerprint during the run.

## Routes

| Route | Role | What it does |
|-|-|-|
| (a) PubMed E-utilities | **authoritative** | ESearch `volume[vi] AND firstpage[pg] AND year[dp] AND surname[au]`, then ESearch on up to 8 title words `[ti]` plus the surname. A hit list with more than 5 results is ignored. EFetch MEDLINE XML for at most 10 PMIDs. |
| (b) Europe PMC, APA `10.1037//` form | lookup key only | Queried only for saved Crossref candidates with a title similarity of at least 0.8. The Crossref record of the `//` twin is fetched too. |
| (c) OpenAlex `title.search` | lead only | Kept when the title similarity is at least 0.85 and the first-author surname is equal. The lead's DOI or PMID must then come back from Crossref or PubMed. |
| (d) Semantic Scholar `search/match` | lead only | Same screen as (c). In the full run it was queried only when (a) and (c) gave no lead. |
| (e) Publisher / JSTOR meta tags | not run | Not built. JSTOR has no public metadata API. |

**How outcomes are judged.** Nothing here uses a new similarity rule.

- New Crossref and Europe PMC candidates are appended to the entry's saved
  evidence. The committed `auto_review.reassess` then judges the result:
  "would verify".
- If that fails, `correction_proposals.single_source_proposal` runs (the S1
  rule, with all its guards): "correction proposal".
- A MEDLINE record without a Crossref twin is judged by
  `pubmed_only_assessment`. It uses the same identity rule
  (`single_source_identity`) and `compare_record`, and the same byline,
  title and loss guards.
  - Extra guards: errata, retraction notices, expressions of concern and
    preprints are never candidates. Any `CommentsCorrections` link other than
    CommentIn, CommentOn or Cites holds the entry. An incomplete author list
    holds it. MEDLINE surnames in capitals are never copied. A journal name is
    never copied from NLM style.
  - A Crossref record that is also identified takes precedence, and the
    entry is held.
  - The venue check accepts the cited venue only when it equals the NLM title,
    the ISO abbreviation or MedlineTA, ignoring case and punctuation.
- Proposals for keys listed in `verification/**/*audit-exclusions.json` are
  withheld, as in Phase 0.

## Results

### Pilot: 40 entries, stratified, seed 20260923, all four routes on every entry

| Route | Found a record or lead | Nothing | Error | Decisive |
|-|-|-|-|-|
| PubMed | 21 | 19 | 0 | 0 |
| Europe PMC `//` | 4 of 8 queried | 4 | 0 | 0 |
| OpenAlex | 22 | 18 | 0 (2 on the first pass) | 0 |
| Semantic Scholar | 25 | 15 | 0 | 0 |

- **Outcomes:** 0 would verify, 0 proposals, 29 held with new evidence,
  11 with nothing new.
- **Requests on the first pass:** 274 network requests (NCBI 94, Semantic
  Scholar 66, OpenAlex 56, Crossref 45, EBI 13) in 4,578 s. Semantic Scholar's
  429 back-off accounted for most of that time.
- **Marginal leads:** Semantic Scholar gave a DOI or PMID that no other route
  had in 6 of 40 entries, and OpenAlex in 8 of 40. None of them led to a
  verification or a proposal.

### Full run: 937 entries

| Outcome | Entries |
|-|-|
| **Would verify** (PubMed record, PMID) | **5**: Lind79 (PMID 419396), MendEtal80 (7395193), SmitEtal79 (228376), Ster69b (5360276), ZeliGile88 (3074313) |
| **Correction proposal** (PubMed record) | **2**: StepEtal05 pages 388 → 388--401 (PMID 16462195; its PubMed DOI has no Crossref record), BoddEtal97 author "P H Beojinga" → "P H Boeijinga", adds "W" to Boddeke's initials, and title "rhytmic" → "rhythmic" (PMID 9135039) |
| Held, audit-excluded | 4: McKoRatc89, MillEtal07d, SinkEtal98, ViemWake91. The current S1 code proposes these from saved evidence alone, but earlier audits hold them. |
| Held, with a new record or lead | 219 |
| Nothing new | 707 |

By target group: `article-no-record` gave 4 verifications, 2 proposals, 112
held with new evidence and 359 with nothing new. `individual` gave 1
verification (Lind79, from `article-too-many-fields`), 4 held
audit-excluded, 107 held with new evidence and 348 with nothing new. All 7
yields came from route (a), and (a) was the only route behind each of them.

| Route (full run) | Found | Nothing | Not requested | Decisive |
|-|-|-|-|-|
| PubMed | 546 | 384 | 0 | 7 (5 verify, 2 proposal) |
| Europe PMC `//` | 14 | 67 | 856 not applicable | 0 |
| OpenAlex | 62 | 35 | 840: the free daily budget ran out | 0 |
| Semantic Scholar | 47 | 34 | 574 skipped (fallback), 282 blocked | 0 |

Of the 477 `article-no-record` entries, 172 got at least one PubMed hit.

**Requests.**

- The cache holds 3,217 successful responses: NCBI 2,186, Crossref 722
  (including 11 copied from the main cache), Semantic Scholar 114,
  OpenAlex 100 and EBI 95. Retried 429 and 5xx attempts are not stored, so
  there were more attempts than that.
- The final full pass made 0 network requests (all 3,155 lookups hit the
  cache).
- **Zero-request repeat** (`--offline`, every request refused): 0 network
  requests, 184.6 s, and outcomes identical to the full run for all 937 keys
  (`results.json` → `offline-repeat.differs_from_full_run` = []). The 1,188
  "attempts_including_refused" are lookups that were never cached, for the
  blocked providers below. They are refused, not sent.

**Provider limits hit during the run.** Each is recorded per row as an error,
never as "nothing found".

- **OpenAlex** now charges unauthenticated use against a free daily budget
  shared by the IP address. After about 100 searches it returned 429 with
  Retry-After of about 69,000 s. Only 97 entries have OpenAlex results. The
  project has no key, and none was created.
- **Europe PMC** returned HTTP 500 or 503 from 02:12 until at least
  03:08 EDT. The APA `//` route and the DOI-linked PubMed corroboration
  are missing for 66 lookups. Re-run when EPMC is back: only those lookups
  go to the network.
- **Semantic Scholar** answers most unauthenticated calls with 429. It was
  made fallback-only, then blocked after entry ~225 of the first full pass.
- **NCBI** returned 4 backend errors as HTTP 200 with an `ERROR` body. The
  generic client had cached them. They are now evicted and retried
  (`extra_sources.forget`).

## Precision checks

- **The 7 yields**, checked by hand against their MEDLINE records:
  - All 5 verifications match title, byline, year, volume and pages exactly.
    Journal equality came from the ISO abbreviation for MendEtal80
    ("Waking Sleeping") and from the NLM title for the others.
  - StepEtal05 completes a one-page range.
  - BoddEtal97 is a real surname typo fix. Its class is the risky
    `author-surname-spelling`, so it needs a spot check.
- **Negative controls** (`tests/test_extra_sources.py`, 25 tests, real
  cached records):
  - Author order differs (BerrEtal02, real citation): not identified.
  - Year changed: not identified.
  - Same title with a different first author: not identified.
  - Real Published Erratum PMID 31059496: never a candidate, so the pair is
    not ambiguous.
  - Real ErratumIn link on PMID 30500813: held.
  - Preprint publication type: not identified.
  - Real PsyArXiv posted-content record for CohnEtal21: does not verify.
  - Real 1933 book review deposited under Bartlett's name with the book's
    title (10.1111/j.2044-8279.1933.tb02913.x): does not verify Bart32 and is
    not identified as an article.
  - Title more than two word edits away (MorrEtal86 vs 10.1038/319774a0):
    not identified.
  - Two identified PMIDs: ambiguous.
  - A Crossref record for the same work: takes precedence.
  - Game62: journal never copied from NLM style.
  - Positive controls: exact and one-field-off citations of real records.
- **Found in passing.** VanSEtal18's byline "J C Van Slooten" parses as
  given name "J C Van", so no identity rule can match it (see the test).
  Unbraced multi-word surnames are a separate cdl.bib clean-up.
- **Not my code.** The S1 rule at HEAD proposes McKoRatc89 title
  "elaborative" → "eleborative" (a registry typo) and SinkEtal98 "test" →
  "tests" with a braced `{Metropolitan-Area}`. Both are audit-excluded here.
  Other callers of `single_source_proposal` must keep applying the exclusion
  list.

## Remaining groups (930 entries, `groups.json`)

| Group | n | Suggested batch decision |
|-|-|-|
| no-record-in-any-source-1960-onward | 199 | Local PDF, else sign-off by journal after a 10-entry sample (13 have only an aggregator lead) |
| record-found-identity-rule-not-met | 141 | One packet: confirm the found record *is* the work (10-sample), then re-run the S1 rules. Sub-patterns: online-first citation with no volume or pages 29, byline differs 29, title case or omitted subtitle 18 (e.g. EckhEtal88: Crossref splits a subtitle and the main title has its own colon), another edition or year 12, rest are journal/coordinate mixes. Each row lists the DOI or PMID |
| identified-record-value-held | 122 | Review packet by sub-reason (value-held 73, coordinates-identity 39, would-not-verify 10) |
| identified-record-differs-in-3plus-fields | 106 | Packet: accept the source record wholesale per entry |
| non-journal-venue-typed-article | 99 | Change the type and route to the proceedings, preprint and JMLR adapters |
| author-count-differs | 92 | PDF or publisher byline check, one packet |
| authoritative-sources-disagree | 88 | Tie-break from the PDF, batch by field |
| pre-1960-no-indexed-record | 28 | Scan or sign-off after a 10-entry sample |
| ambiguous-identity | 23 | Human choice of record |
| individual-other | 19 | Individual (year conflicts, audit exclusions, external evidence) |
| conference-abstract-typed-article | 9 | Removal list (user decision 2026-09-22) |
| citation-byline-more-detailed-than-source | 4 | Join the Phase-0 byline batch |

## Conclusion

The new sources barely shrink the backlog: 7 of 937 entries, all from
PubMed MEDLINE records of pre-DOI or unregistered-DOI articles. OpenAlex and
Semantic Scholar mostly re-find DOIs that Crossref already holds, and add
nothing decisive. The largest new actionable set is the 141 entries where
a real record was found but the strict identity rule fails. That is a
grouped human decision, not an automatic one.

## Reproduce

```
.venv/bin/python verification/extra-sources-2026-09-23/measure.py --pilot          # 40 entries, all routes
.venv/bin/python verification/extra-sources-2026-09-23/measure.py --block api.semanticscholar.org api.openalex.org www.ebi.ac.uk
.venv/bin/python verification/extra-sources-2026-09-23/measure.py --offline         # zero-request repeat
.venv/bin/python verification/extra-sources-2026-09-23/measure.py --keys KEY ...    # print rows only
.venv/bin/python -m pytest tests/test_extra_sources.py
```

The contact address is `CROSSREF_MAILTO` or the one already in cached
Crossref requests (jeremy.r.manning@dartmouth.edu). NCBI requests carry
`tool=bibcheck` and that address. Note that the `--pilot` section of
`results.json` was regenerated from cache after the first pass. The
first-pass request counts are the ones quoted above.
