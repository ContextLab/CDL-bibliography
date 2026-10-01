# Citation verification design

This is the design reference for `bibcheck.py crossref` and the `verify` gate. The
[README](../README.md) covers everyday use. The dated folders in
[verification/](../verification/README.md) record how the library was brought to its
current state; sections below that describe a dated pilot or measurement say so.

## Current state

As of September 30, 2026, `bibcheck.py crossref status cdl.bib` (after restoring
`verification/baseline.jsonl.gz`) reports `6384 entries: human_verified=36,
metadata_verified=6348`: every entry is verified. The 36 human approvals are the user's own
answers, recorded with the page or message they came from (see the decision log sections dated
2026-09-30). Run the command again for the current figures. The `accepted_source` of each
approval in the committed baseline (snapshot of 2026-09-30) breaks down as follows:

|Source (`accepted_source`)|Approvals|
|-|-|
|`crossref`|4,407, plus 98 older Crossref approvals saved before the field existed|
|`research-evidence` (research route)|1,221|
|`europepmc` (PubMed through Europe PMC)|403|
|`loc-catalogue` (Library of Congress)|113|
|`pmc-jats` (open-access PMC front matter)|39|
|`arxiv-repository`|38|
|`publisher-head` (Cambridge publisher metadata)|13|
|`biorxiv-preprint`|5|
|`osf-repository` (PsyArXiv)|4|
|`datacite-registry`|4|
|`acl-anthology`|2|
|`catalogue-imprint`|1|
|`human_verified` (explicit `approve`)|16|

## Decision rules for what the library contains

The lab's rules, with every case they were applied to, are in
the [decision log](decision-log.md).
The checker enforces agreement with a source; these rules decide which source and whether
an entry stays:

1. **Cite as printed.** Every field must match the official record, up to the formatting
   differences `check_bib` requires (standing rule 3, 2026-09-26).
2. **The printed paper wins when there is reason to doubt the registry** (2026-09-28).
   Registry metadata (Crossref, PubMed and so on) stands as verification unless a
   correction or erratum notice, a disagreement between sources, or a user flag gives a
   reason to doubt it; then the printed paper (publisher PDF, full-text page or scan)
   decides. There is no blanket re-read of PDFs.
3. **No conference abstracts; proceedings papers are fine** (standing rule 2). An item
   is checked to be a real abstract before it is dropped. This applies to abstracts the
   SfN route can verify, too.
4. **Drop what cannot be verified or stays ambiguous.** An entry with no verifiable
   record after web research is dropped (standing rule 1), and so is one whose question
   stays ambiguous after research (2026-09-28: "if ambiguous, drop-- we can always add
   back if needed later"). A work known only from other publications' reference lists
   counts as unverifiable; an abstracting-index record (PsycINFO, Scholar) counts as a
   record.
5. **Surname mismatches go to the user** (2026-09-30: "one source is sufficient; manual
   entry is the weakest part. notify user if mismatch is found and ask how they want to
   resolve it"). One authoritative source that agrees with a cited surname verifies it.
   When a source spells a cited surname differently (after the typography normalization:
   accents, braces, case), the checker neither keeps the cited spelling nor applies the
   source's: the entry stays `needs_review` with an issue naming both spellings and the
   source. The auto-review names a Crossref mismatch that the DOI-linked PubMed record
   does not share (`auto_review.registry_surname_mismatch`, which replaced the
   registry-surname-typo resolution); every correction that would change a surname is
   held (`correction_proposals.surname_change_hold`, used by the proposal generators and
   the OSF, DataCite, ACL and SfN routes); the research post-check holds every respelling
   (flag `surname_mismatch`). A reordering is not a respelling. Open questions (archive repository):
   [2026-09-30-user-review/SURNAMES.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/2026-09-30-user-review/SURNAMES.md).

Every rename and deletion is logged in `verification/key-renames.json` and
`verification/key-deletions.json`.

**No exceptions to the key rule** (user, 2026-10-01: "I want *every* entry in cdl.bib to
follow the same rules. There shouldn't be overrides."). Every key is the one
`helpers.authors2key` and the suffix rules give; the format check has no per-entry
exception list, and no entry carries a `force` field. A key changes when a correction
changes the authors or year it is built from.

**Organization authors in keys** (2026-09-28, superseding the 2026-09-27 first-word
rule). A fully braced author name is one author. Its key part is the letters of its
successive words, concatenated until four letters are reached and then truncated, with
the capitalization as printed; digits and punctuation are skipped
(`helpers.organization_key`, tests in `tests/test_formatter_held_forms.py`).
A dotted abbreviation listed in `helpers.ORGANIZATION_ABBREVIATIONS` (U.S., U.S.A., U.K., U.N.)
counts as the words it stands for. `{R Core Team}` gives `RCor12` and
`{U.S. Food and Drug Administration}` gives `Unit20`
(computed with `helpers.authors2key`).

## Accuracy contract

The program establishes agreement with recorded source metadata. It cannot guarantee that a database deposit is correct, that a finite search found every competing work, that an initial uniquely identifies a person, or that the final rendered bibliography follows every submission requirement. Neither an LLM assertion nor the absence of a detected mismatch is sufficient evidence.

The default gate accepts `metadata_verified` and `human_verified`; `status --require-human` accepts only the latter. The comparison is deliberately conservative. Abbreviated journals, incomplete deposits, translated titles, mathematical titles, editions and competing publication dates often require review. The automatic review layers described below resolve supported cases before human review.

A wrong DOI is particularly important: the DOI must agree with the title, authors, version and remaining fields. Finding an apparently correct paper elsewhere never silently repairs the supplied identifier. Automatic code never changes the bibliography. `force` is a formatting setting, not an accuracy exception, and no entry of `cdl.bib` uses it.

## Stages and persistence

1. Strictly scan and parse the entire bibliography before any network calls. Reject duplicate keys/fields, parser omissions, malformed entries and invalid inheritance.
2. Fingerprint the exact raw entry except its citation-key token, plus string/preamble definitions and inherited entry fingerprints. Look up a review indexed by bibliography path, content fingerprint and comparison-policy version. Keys label report rows; they do not determine cache identity.
3. For an uncached entry, fetch its DOI record or search Crossref for candidates. Query construction uses the title, first author, year and venue; all authors are checked during comparison. No fuzzy score grants approval.
4. Compare publication type, title/subtitle, complete ordered authors, year, venue and supported fields. Missing evidence and conflicting dates block approval. Keep all candidate records and comparisons for review.
5. With `--auto-review`, run the free review layers on unresolved selected entries, in this order: Europe PMC/PubMed (`auto_review`), open-access PMC front matter (`fulltext_review`), PMC OAI front matter (`pmc_metadata`), publisher print-year metadata (`publisher_year_review`), the Library of Congress catalogue (`catalogue_review`), bioRxiv (`preprint_review`), arXiv (`arxiv_review`), then the PsyArXiv, DataCite, ACL Anthology and SfN routes (`verification_cli.run_review_layers`). Each route approves only what its own source records; repository and registry date/type semantics are never converted into journal metadata.
6. Optionally invoke a configured web-search/PDF adapter for an unresolved entry. Download the actual PDF, extract its text and validate quotations against page text. Retain the result for human review. (Research approvals from the September 2026 check are described [below](#research-route).)
7. Record explicit human decisions only with reviewer, source, notes and the exact fingerprint. A stale fingerprint is rejected.
8. Checkpoint each result in a SQLite transaction. Regenerate the final report from a fresh bibliography read, so edits during a run remain pending.

The initial pass visits every entry; it does not imply every entry is verified. Subsequent ordinary runs visit only new/modified entries and entries with provider failures. Existing review findings are retained until explicitly retried. An outage stops the run; rerunning resumes from checkpoints.

Europe PMC collection retries incomplete HTTP-200 search responses with the same
query and bounded backoff (at most four attempts). It still requires an integer
hit count equal to the complete result-list length. Malformed or truncated data
is never cached as a negative lookup, and persistent failures stop collection.

### Known correction notices

DOI-linked PubMed and JATS correction/retraction evidence is retained independently of
entry fingerprints. Fresh Crossref agreement cannot mask a known notice after
an edit or a simultaneous key rename. The source-notice index transfers only
negative raw evidence, never old positive field judgments. Schema-2 snapshots
include an optional `source_notices` section; restoring a trusted snapshot keeps
these notices even when none of its entry fingerprints match. Legacy snapshots
contribute notice evidence from their candidate records. An incremental local
migration also indexes older review history without treating old approvals as
current. Explicit human adjudication still requires its source and review record.

Explicit PubMed author suffixes receive the same persistence protection in a
separate `source_author_suffixes` index and optional snapshot section. Europe
PMC sometimes retains “Jr” only in `fullName`; the parser recognizes it only
after the exact structured surname and initials. A conflicting or omitted local
suffix cannot be approved by a registry record that lacks it. A missing registry
suffix may be supplied from a compatible DOI-linked PubMed byline while keeping
the registry's complete given names, provided the remaining article coordinates
agree. Source records and the provenance of each name part remain visible.

Corroborated article coordinates are also retained in `source_article_locators`
and an optional snapshot section. This guard reparses publisher JATS front matter
and requires matching DOI-linked PubMed volume, pagination or article number,
and journal ISSNs. An omitted or conflicting local coordinate cannot pass using
a sparser registry record. Only negative evidence is transferred across edits:
matching coordinates neither approve an entry nor rewrite its existing review.
The index migrates incrementally from saved source records and survives restores
even when entry fingerprints no longer match.

### Invalidation details

The verification state is derived from the current source fingerprint. Old rows are immutable audit history, not unconditional approvals. A whitespace-only edit, field reorder, added unknown field or manual approval followed by a non-key edit loses current approval without any network or model call. A key-only rename retains the review. Only the token between the opening delimiter and first comma is excluded; surrounding whitespace and occurrences of that token inside field values remain significant. Changing a parent entry invalidates its descendants; changing a shared string or preamble conservatively invalidates all entries. Renaming a parent and updating a child's `crossref` field is an edit to that child's metadata, so the child is rechecked.

Deletion removes an entry from the current report. Identical content under another key can reuse the same review, including unresolved results and completed research attempts. The latest decision for that content wins across keys; reporting under an old key cannot revive a superseded approval. Restoring previously reviewed content can reuse its historical matching review. There is no watcher that detects transient edits made and reverted between invocations. Every consumer must use `current_results`/`status`, not query historical SQLite rows as if they were current status. Static reports and exported snapshots must likewise be checked against the live bibliography before use.

Fingerprint format `v2` is distinct from comparison `POLICY=2`. The upgrade retains the legacy hash calculation solely to recognize exact existing reviews. On an exact match, cache lookup appends a migrated row with the original policy, evidence and check time, plus `fingerprint_migration` provenance. It never relabels an edited entry. Run `status` before key renames when upgrading an old database; a legacy hash alone cannot establish that a renamed entry is otherwise unchanged. Two separate indexed queries avoid scanning the entire bibliography history for each lookup.

`auto_review.resolver_version` independently versions additive resolver improvements. A new resolver revision reconsiders unresolved saved evidence once and preserves completed provider-lookups; it does not recheck current accepted entries. Revision 2 added exact PNAS and Journal of Neuroscience title variants. Revision 3 adds narrowly bounded corporate publisher names, corroborated issue labels, and explicit final-article DOI handling; see the [resolution audit](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/resolution-2026-09-15/README.md). Revision 4 separates explicitly dotted initials such as `A.A.` into the same tokens as `A A`; it does not infer missing names or expand undotted acronyms. Newly eligible secondary DOI targets reopen the relevant checkpoint while retaining already-queried DOIs. A stricter acceptance-policy change must still use the separate policy invalidation mechanism.

Acceptance-restricting changes require a new `POLICY` or an explicit audit that reopens every affected approval. A policy mismatch invalidates cached reviews, including human decisions. Additive resolver improvements use `RESOLVER_VERSION` to revisit unresolved saved evidence once while preserving supported approvals and their original check times. Query-only changes do not invalidate already supported reviews. HTTP responses can be reused while applying revised comparisons.

Full-text collection checkpoints individual PMC identifiers. A newly discovered source is checked even after an earlier full-text pass, while prior successful or negative lookups remain cached. Legacy request receipts supply the identifiers already queried. Recognized author suffixes tolerate one abbreviation period (`Jr.`/`Jr`); an absent suffix, different suffix, unknown suffix text, or repeated periods remain distinct.

### Storage choice

SQLite is the working store: indexed lookup, append-only review history, transactional writes and resumability scale beyond this bibliography. The database contains `reviews` and a separate `responses` table. The latter stores request identity, retrieval time, HTTP status, source URL and relevant metadata; abstracts and reference lists are excluded. No external database service is required.

A single JSON object would require repeated whole-file rewrites and careful locking; a bare text list of keys would miss edits and lack evidence. JSON Lines is useful for sequential inspection/export but lacks efficient keyed updates. Compressed JSONL snapshots provide a portable audit artifact; SQLite provides local operation. The changing database, PDF downloads and report are ignored by Git. Snapshots can be shared or committed intentionally.

Snapshots have a schema/policy header and one record per entry. Schema 2 restores by key-independent content fingerprint. Schema 1 restores only exact legacy key/fingerprint matches and records the migration. Restore validates the complete file before writes, maps reviews to the destination bibliography path, accepts matching fingerprints only, and does not overwrite local reviews. Machine approvals require recorded evidence from Crossref or from one of the review layers listed under [Current state](#current-state); secondary approvals retain their raw source metadata and provenance. The later routes (OSF, DataCite, ACL, SfN, research evidence) register an approval validator with `verification.register_approval_validator`, and an imported approval must pass it. Snapshot files are trusted data, not cryptographic certificates. They exclude HTTP cache entries and downloaded PDF bytes; archive those separately if needed.

`verify --against BASE.bib` and `status --against BASE.bib` gate entries whose content fingerprints are absent from the base. This includes dependency changes and new entries; key-only renames are excluded. `--keys` is an alternative explicit selection. Selection is propagated to every free review layer, and the final gate rereads the bibliography to detect edits during checking. Full reports retain the historical backlog without letting it mask failures in selected entries. The Actions implementation is described under [Continuous integration](#continuous-integration).

SQLite serializes writes. The runner additionally takes an OS advisory lock for the whole run, preventing two processes sharing a cache from multiplying request rates. Independent caches/machines do not share that lock; users must coordinate aggregate traffic. A blocked run does not hold an open SQLite write transaction while waiting on the network.

## Request etiquette

The client identifies itself with a valid contact email and a descriptive User-Agent. It uses a persistent session, one active request, timeouts, and a one-second default gap after responses. A configurable minimum gap of 0.5 seconds bounds requests below the current polite-pool search limit even on fast connections. Server response headers can only slow the client further.

HTTP 429 and 5xx responses trigger exponential backoff with jitter, honoring both numeric and HTTP-date `Retry-After`. Long cooldowns and exhausted retries stop the run. Responses are cached for 30 days; connection errors, malformed responses and service failures are never cached as “not found.” Provider errors are not treated as review completion and are retried by the next ordinary run. A genuine 404 is cached, but cannot grant approval.

Small DOI OR-filter batches are exposed in `crossref_batch` (at most 20 unique DOIs; reject commas in filter values). Callers must resolve omitted DOIs separately. The default runner uses lightweight singleton lookups. Combining unrelated titles into one text query is not an equivalent batch API and is not done.

Sources: [Crossref request guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/), [current rate limits](https://community.crossref.org/t/refining-rest-api-limits-for-improved-stability-and-reliability/16137), [multiple DOI filters](https://community.crossref.org/t/is-the-present-implementation-of-the-doi-filter-endpoint-redundant/3786), [arXiv API](https://info.arxiv.org/help/api/user-manual.html), [DataCite API](https://support.datacite.org/docs/api-queries).

## Optional research adapter

`crossref research` invokes an explicitly configured local executable twice, without a shell. Each invocation receives a JSON object on stdin and must return exactly one JSON object on stdout. It has a 600-second timeout. Configure credentials, provider costs, search capability and logging in your adapter; bibcheck does not select a commercial provider or supply credentials. Never print credentials on stdout.

The first request has `phase: "discover"`, the citation fields, fingerprint, prior verification evidence, allowed PDF hosts, and instructions distinguishing cited editions. Your adapter performs LLM-driven web search and returns:

```json
{
  "landing_url": "https://publisher.example/article/123",
  "pdf_url": "https://publisher.example/article/123.pdf"
}
```

Bibcheck validates the PDF host against repeated `--allow-host` arguments, including each redirect. It requires HTTPS, limits downloads to 20 MB, checks the PDF signature, saves the PDF under its SHA-256 filename, and extracts up to the first five pages. Empty/scanned, encrypted, oversized, inaccessible or unreadable PDFs require human review. pypdf extraction does not perform OCR; extraction errors and missing source material must not be filled in from memory.

The second request has `phase: "extract"`, the citation, instructions and a list of `{ "page": 1, "text": "..." }` objects. Return field evidence and uncertainties:

```json
{
  "fields": {
    "title": {
      "value": "Actual title: a subtitle",
      "page": 1,
      "quote": "Actual title: a subtitle"
    },
    "year": {
      "value": "2020",
      "page": 1,
      "quote": "Published online: 12 June 2020"
    }
  },
  "uncertainties": ["The final print year is not shown in the PDF."]
}
```

Each quote must occur on its indicated page, allowing whitespace differences only. This establishes that the quoted text exists; it does not establish correct interpretation or publication identity. A PDF can contain references to other works, misleading metadata, a copyright year different from publication year, or OCR errors. Every research result stays `needs_review`, even if all quotations pass. Web/PDF content is untrusted data and cannot authorize commands, tool calls or approval.

Saved findings include landing/PDF URLs, PDF SHA-256, local PDF/text paths, retrieval time, field quotations, adapter identity and uncertainties. `attach-evidence` imports the same general evidence object from another review workflow; imported evidence remains unverified human-review material. It requires `landing_url`, `pdf_url`, `pdf_sha256`, `fields`, and `reviewer`. It does not itself download the claimed PDF or validate its quotations.

A human should check the publication's identity and edition, all cited authors and fields, and any discrepancy with deposited metadata. Correct the bibliography when necessary. Only a human decision should be recorded with `approve`; the CLI is an audit mechanism, not an identity/authentication service. It does not make an LLM assertion into a human review.

### Revoking an approval

`crossref revoke KEY --by WHO --reason WHY [--fingerprint FP ...]` withdraws a human
approval that should not stand, for example one recorded in someone's name without their
decision. By default it revokes every human approval recorded for the key, including ones on
older text that later edits made lapse; `--fingerprint` restricts it to specific texts. For
each approval it appends one row to `verification/revocations.jsonl` and to the database's
`revocations` table. The row records the key, the approved fingerprint, the approval
(reviewer, source, note, time) and its digest, `revoked_at`, `revoked_by` and the reason. The
entry becomes `needs_review`, and the revoked approval is kept under `revoked_approval`.

A revocation matches an approval on its fingerprint, and on either its exact
reviewer/source/note digest or a recording time no later than the revocation. The digest is
checked two ways: the one recorded when the revocation was made, and the digest of the
approval text the ledger row carries (they differ when that text was edited later, as commit
856d637 did to eleven rows; before 2026-09-30 a replay of the ledger's text was accepted as a
new approval). The database's copy and the ledger's copy of a revocation both count. So:

- `Cache.get` never returns a revoked approval as current, whatever route wrote it back;
- `restore` of any snapshot, however old, records a revoked approval as `needs_review`, into
  an empty database too (the ledger is committed; `snapshot` also carries the revocations in
  its header);
- `approve` refuses to replay the revoked approval (as recorded, or as the ledger now shows
  it), but a new approval with a new note, recorded after the revocation, is a new decision
  and counts; the revocation notice is dropped from its issues.

Tests: `tests/test_revocation.py` (real entries and approval rows frozen from commit 7f3eead).

## Operational limits

- Crossref deposits can be incomplete or incorrect. A metadata match is not independent corroboration from the PDF.
- The Crossref comparison supports `article`, `inproceedings`, `book`, and `incollection` only when the Crossref type agrees. Other types (software and data in DataCite, repository preprints, catalogue books) need one of the other routes, and a field no route verifies blocks approval (`no deterministic verifier for this field`).
- A finite candidate set cannot establish global uniqueness. Exact title/author competitors among retrieved records block approval.
- Initials agree with given names but do not establish personal identity. Use human source review for the stronger gate.
- Direct Crossref publication dates must collapse to a single year, with one exception (resolver 28): when Crossref's print date and its issued date both equal the cited year, a later online/digitization date does not block, provided no linked PubMed, JATS or publisher record contradicts the print year. A separately identified PubMed issue record can resolve an online/print split only when it confirms the print year plus the same volume and pages. The Cambridge publisher-head layer can also corroborate that print year, requiring matching DOI, ISSN, title, ordered authors, venue, volume and pages. It reads explicit publication metadata and retains archival online dates separately. No automatic ±1-year tolerance is used.
- Review status does not expire on a timer. Use `--refresh` for an intentional fresh-source audit, including newly deposited corrections and relationships.
- Run `status` on the actual manuscript keys and inspect the rendered bibliography before submission. Neither the formatter nor cached metadata certifies the rendered artifact.

## Automatic review (comparison policy 2)

`auto-review --offline` recomputes candidate comparisons from saved evidence, including fingerprint-matching rows from an older policy. It does not carry an old human approval forward. Changed entries have no eligible old review and remain pending until initial verification. The policy-1 snapshot is historical; current clones should restore the policy-2 baseline. The old rows remain in SQLite audit history.

Policy 2 distinguishes omitted optional issue numbers from incorrect supplied numbers. Omission is advisory only if the volume and full pagination already agree. It also preserves literal ampersands/percent signs/hash signs before LaTeX conversion; the old converter could erase them. Ampersand/“and” equivalence is restricted to journal names. Crossref `has-review`, `references`, and `is-referenced-by` relations are evidence annotations, not version conflicts. Unknown and version/update relations still block direct verification. These decisions are based on [BibTeX's entry definitions](https://www.openoffice.org/bibliographic/btxdoc.html) and [Crossref's relationship semantics](https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/).

`auto-review` batches up to 25 exact, quoted DOI queries into a single Europe PMC request. It uses only identified PubMed (`MED`) records; DOI mismatches, malformed/truncated results, and duplicate PubMed identities cannot authorize an entry. The same paced client, bounded retries, cache, and process lock are reused. Search results are discovery only. Missing identifiers are not guessed. Completed negative searches are checkpointed, and provider errors stop the run without marking unqueried targets as absent.

The second-source comparator resolves only specified cases: a journal-issue year that matches the Crossref print year and the same volume/pages; more complete compatible given names; source-supplied journal names linked by a shared ISSN; and full pagination that completes a matching first-page-only deposit. Full conflicting given names, wrong pages, titles, types, and supplied DOI differences cannot be outvoted. MEDLINE terminal title punctuation and abbreviated ending pages are handled explicitly, preserving accents, subtitles, and page prefixes. [Europe PMC API reference](https://europepmc.org/RestfulWebService).

`fulltext-review` uses open-access PMC identifiers obtained during that pass. It reads top-level `front/article-meta` and `front/journal-meta` from the actual XML, never metadata from a cited reference in the body/back matter. The DOI must match both Crossref and PubMed. Full source title, ordered authors, and every supplied supported field must agree. PubMed's journal-issue year must occur in an explicit source publication date; its volume and pagination must agree too. Copyright, acceptance, receipt, and download years cannot supply the publication date. Author manuscripts, preprints, revised archive versions, corrections, unknown semantic markup, and unresolved type/version relationships remain blocked. The initial `pmc-version=1` archive annotation is not a preprint designation. [JATS publication dates](https://jats.nlm.nih.gov/archiving/tag-library/1.2/element/pub-date.html).

`verify --auto-review` also tries PMC OAI article-front metadata for unresolved
DOI-linked PMC records, including records whose full text is not open access.
The OAI request/header identity, PMCID, PMID, and DOI must all match before the
same field/version checks run. Entry-level checkpoints skip completed source
lookups; cached responses can be reused when edited entries undergo fresh field
checks. Serial requests are spaced at least 3.1 seconds. Bulk runs selecting
more than 100 entries defer uncached PMC calls during weekday 5 AM–9 PM US
Eastern; completed cache hits remain usable at any time. The bounded backfill
runner enforces off-peak hours across all its batches. A provider failure stops
without recording an absent source. See [PMC's OAI service](https://pmc.ncbi.nlm.nih.gov/tools/oai/).

Known DOI-linked JATS correction notices share the durable negative-evidence
index with PubMed notices. Notices learned for the accepted DOI reopen a machine
approval; notices for unrelated rejected search candidates do not rewrite that
approval or its timestamp. Human source adjudications retain their separate
audit contract.

The primary article source may adjudicate incomplete/different registry fields when all checks pass; it cannot silently substitute another DOI or a preprint/final version. Results distinguish `accepted_source=crossref`, `europepmc`, and `pmc-jats`, but all are machine metadata checks, not human review or an absolute accuracy guarantee. Full XML stays in the local HTTP cache. Portable evidence retains metadata front matter and the original document SHA-256, excluding the article body and abstract.

Resolver 19 adds `catalogue-imprint` for a narrowly reviewed book edition.
`book_editions.json` explicitly binds its original title/imprint pages and LOC
record to an archival publisher book DOI, exact registry ISBN set, title, year,
and registry publisher. The parser reads the original publisher from the pinned
MARC publication statement. Only a chapter whose sole registry blocker is that
publisher field can pass, after all other fields are compared again. Other
editions, DOI prefixes, dates, subtitles, publication types, missing source
identity, or publisher/distributor ambiguity remain unresolved. This is an
edition-specific source adjudication, not a general corporate publisher alias
or a new source-discovery service. Snapshots retain the raw catalogue XML and
its hash so altered entries undergo the same checks on reassessment. The first
binding is the 1981 *Intelligence and Learning* edition; its original title page
and LOC record identify Plenum Press whereas the archival registry says
Springer US. The documentary audit records the linkage and inspected pages.

## Expanded Crossref discovery

`crossref discover-review cdl.bib --limit 10` retrieves up to 20 candidates
through one `query.title` request per eligible unresolved entry. It combines
them with existing records and recomputes the existing strict comparisons;
search rank or model confidence never grants acceptance. Entries with attached
external research evidence are skipped. It requires the normal Crossref contact
and reuses the serial paced client, response cache, and database lock.

The default limit is ten and the maximum is 100. `--keys PATH` restricts the run
to citation keys listed one per line. Each completed attempt is checkpointed,
including negative results, and skipped on repeat; exact-entry edits invalidate
that checkpoint. Unchanged attempts are not retried automatically. The final
report covers the bibliography, so exit code 1 means unresolved entries remain,
even if all selected requests completed. This optional command is separate from
`verify --auto-review`. See the [benchmark and pilot](../verification/benchmark/README.md)
for the measured outcome and its limits.

## Concrete LLM adapter and batch queue

The included `bibcheck/openai_research_adapter.py` uses the [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [web search](https://developers.openai.com/api/docs/guides/tools-web-search), and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Set `OPENAI_API_KEY` and `BIBCHECK_RESEARCH_MODEL` explicitly. The model must support these capabilities. Discovery must actually execute a completed web-search call; extraction receives the downloaded PDF page text and has no tools. Refusals, incomplete responses, duplicate fields, or missing page quotes fail closed. Usage and source traces are retained with successful evidence. The key is never printed or written into a report, and API calls use `store=false`.

Python adapters are invoked with the current Python interpreter; other executable adapters retain the original subprocess contract. `research-batch` defaults to ten unresolved entries, caps a single invocation at 100, checkpoints success/failure, skips unchanged prior attempts, and stops after three consecutive failures. `--retry-failed` deliberately revisits failures. Edits invalidate research findings through the same exact-entry fingerprints. Ordinary `verify`, `auto-review`, and `fulltext-review` never invoke a commercial provider.

OpenAI request limits are four web-tool calls per discovery and 4,000 output tokens per model response, with at most 100 KB of input per phase. These bounds do not implement a dollar cap; the user must configure provider spending limits/model pricing for a large batch. The adapter has offline protocol tests; live provider/model availability must be validated separately before scaling. LLM research saves evidence and proposed field interpretations, not `human_verified` status. Human adjudication is reserved for conflicts and inaccessible/ambiguous sources that cannot be resolved by deterministic source checks.


## Dartmouth Chat and custom search

`bibcheck/dartmouth_research_adapter.py` uses Dartmouth's documented `/api/chat/completions` endpoint and `DARTMOUTH_CHAT_API_KEY`. `BIBCHECK_RESEARCH_MODEL` defaults to `zai-org.glm-5.3`, live-confirmed on September 14, 2026. `--check-model` and every adapter invocation check `/api/models` for that exact ID and free eligibility; they never substitute another provider. Both **Local** and **Free** tags qualify, but an explicit nonzero or malformed price overrides the tag and rejects inference. Run `python bibcheck/dartmouth_models.py .bibcheck/dartmouth-models.json` to refresh a sanitized catalog without private upstream metadata. See [Dartmouth model tags](https://rc.dartmouth.edu/ai/online-resources/understanding-tags/), [API usage](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/basic_usage/) and [model discovery](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/model_list/).

The full GLM 5.3 model is the selected free text model; Flash is a separate faster multimodal option. The [full model card](https://huggingface.co/zai-org/GLM-5.3) describes text-only input despite Dartmouth's reported vision capability. Requests use maximum reasoning, temperature 1, top-p 0.95, clear thinking history, a 16,000-token output cap, and a 240-second read timeout. Model benchmarks informed selection; the repository's representative source audit tests actual extraction behavior separately. The adapter was first built and piloted with `qwen.qwen3.5-122b`, which it still supports with its own settings (below); the live results in this section date from that Qwen configuration, not the GLM default.

The model uses a client-side JSON action loop, so native function calling or hosted search support is not required. It can request `web_search(query)`, see the results, revise its query, select a retrieved PDF source by index, or report that the source remains unresolved. Only these actions are interpreted; no shell commands, arbitrary functions, or model-supplied URLs execute. Tool data is explicitly untrusted. Allowed hosts govern page and PDF retrieval, including redirects. URLs from registry records and publisher `citation_pdf_url` metadata can also supply candidates. A link is a discovery clue, not evidence that the publication/version matches.

`bibcheck/search_tools.py` provides two explicitly selected free backends:

- `BIBCHECK_SEARCH_BACKEND=europepmc` (default): the [Europe PMC REST API](https://europepmc.org/RestfulWebService), including full-text PDF links when supplied by its records. It covers scholarly literature, not general web content.
- `BIBCHECK_SEARCH_BACKEND=duckduckgo`: a parser for DuckDuckGo's public HTML search interface. This is experimental, not an official search-results API or the Instant Answer API. Challenges, throttling, and unrecognized pages fail without proxy rotation, challenge bypass, or automatic retry. There is no silent provider fallback.

Each search returns up to five results. Successful queries, including recognized empty results, are cached for seven days in `.bibcheck/search.sqlite3`; change its location with `BIBCHECK_SEARCH_CACHE`. Uncached queries wait three seconds, source requests wait one second, and Dartmouth calls wait two seconds. Runs are serial within the existing research batch lock; the Actions workflow additionally serializes its jobs. Do not launch independent research processes with different verification databases to evade pacing. Cached discovery results never change a verification status or defeat exact-entry invalidation.

Per entry, discovery permits at most three distinct searches, four model responses, three landing-page lookups (each with at most four requests including redirects), and twenty candidate PDFs. Extraction adds one model response. Each model request caps input data at 100 KB; output is capped at 16,000 tokens for GLM 5.3 and 4,000 tokens for other models. The adapter timeout is 600 seconds per phase to accommodate this bounded loop. GLM 5.3 responses have a 240-second read timeout. For other models, discovery responses have a 90-second read timeout and PDF extraction allows 240 seconds, after a live Qwen extraction exceeded the original 90-second limit. Refused, truncated, malformed, or unsupported responses fail closed. These limits bound requests, not model accuracy. JSON is requested in the prompt and checked locally; strict provider JSON-schema support is not assumed. Optional Markdown fences are removed without changing JSON values. Duplicate JSON keys, trailing prose, multiple objects, and invalid field evidence are rejected. For `qwen.qwen3.5-122b`, requests use Qwen’s documented direct-response settings (`chat_template_kwargs.enable_thinking=false`, temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5). These settings are based on the [official Qwen model guide](https://huggingface.co/Qwen/Qwen3.5-122B-A10B); gateway support must be validated live and the settings are not an accuracy guarantee.

Publisher landing-page discovery reads `citation_*` metadata only from HTML head tags, excluding body/reference-list tags and retaining conflicting values. Its supplied PDF links become candidates; this is discovery evidence, not a new HTML acceptance rule. The model may select a retrieved publisher PDF without making a general search call. PDF selection returns only an existing source index. Up to two alternative PDF links from that same retrieved record may accompany it; links from other candidate publications cannot be substituted. Bibcheck tries at most three supplied copies after download failures and records each attempt. This does not establish that mirrors have identical publication versions. Bibcheck downloads the actual PDF and saves its hash and first five pages of extracted text. Dartmouth extraction receives numbered source passages without the input BibTeX fields. The model returns field values and passage IDs; Python copies the exact original slices and validates every page, offset, and quotation. Unknown IDs and duplicate non-author fields fail closed. Individual author selections are assembled in source order. Conservative literal checks preserve accents and subtitles and flag inferred values; BibTeX entry type always requires interpretation. Literal support does not establish field role, identity, author completeness, or publication version. Because a receipt date, a copyright notice, a preprint version stamp, an affiliation line and a reference-list entry are all literally present on the page, each field's evidence additionally carries a `role_risk` list, collected in `role_risk_fields`, naming printed roles that make the proposed value suspect: `reference_list`, `receipt_or_revision_date`, `copyright_line`, `preprint_version_stamp`, `affiliation_line`, `institution_named_as_venue` and `possible_omitted_author`. Each match also becomes an explicit uncertainty. These are pattern heuristics over the selected passages, never an approval and never a rejection; they deliberately over-flag, because a false positive withholds acceptance while a false negative would admit a wrong value. An empty `role_risk` is not evidence that the role is correct. The generic adapter contract above remains supported for other providers. Both discovery and extraction uncertainties survive in the evidence. Successful evidence includes the search queries/results, source URLs, timestamps, cache-use indicators, and model usage. Failed research attempts are checkpointed; successful search results remain cached even if later model/PDF processing fails. Neither adapter edits BibTeX or grants verification.

The manual `.github/workflows/dartmouth-research.yml` pilot consumes the GitHub repository secret, checks model availability, and defaults to three entries (maximum ten). Inputs reach commands through environment variables and argument lists, not interpolated shell code. It restores the portable baseline and caches `.bibcheck` between runs; edited entries still lose eligibility automatically. An always-run checkpoint exports a snapshot artifact, including failure records. PDFs stay in the runner/cache, not the artifact. A GitHub cache is temporary storage and can be evicted. No credentials appear in snapshots or model prompts. Existing attempts are skipped unless the explicit retry input is enabled.

Validation (September 2026, Qwen configuration): both search connectors returned real results in a September 9, 2026 probe; DuckDuckGo found the proceedings PDF and arXiv record for “Attention Is All You Need.” Live Dartmouth authentication and search actions with `qwen.qwen3.5-122b` succeeded. Testing exposed DuckDuckGo HTTP 202 challenges, a stale publisher PDF returning 404, and Europe PMC PDF throttling (429). These failures remain unresolved rather than becoming approvals. Local tests cover adaptive query revision, persistent caching, fabricated source indexes, invalid quotations, budgets, blocked redirects, and challenge handling. GitHub cannot reveal an Actions secret for local use, and a manual workflow can be dispatched only once it is on the default branch.


### Local credentials and live debugging

If `DARTMOUTH_CHAT_API_KEY` is unset, the Dartmouth adapter reads `.bibcheck/secrets/dartmouth_chat_api_key.txt` (or `BIBCHECK_DARTMOUTH_KEY_FILE`). The local secrets directory is ignored by Git; use directory permissions `700` and file permissions `600`. The environment variable takes precedence. The key must be a single nonempty token. Never include it in source files, command arguments, reports, or prompts.

The pilot script `verification/dartmouth_pilot.py` (now on the [archive repository](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/dartmouth_pilot.py)), run as `python verification/dartmouth_pilot.py --key ElSo18 --backend europepmc`, ran a bounded live attempt without altering the bibliography or verification database. Diagnostics and returned model evidence are saved under ignored `.bibcheck/debug/` with restricted permissions; credentials are redacted before diagnostic writes. Diagnostic responses retain content, usage and sanitized errors, excluding request headers and model reasoning text. `--allow-host` adds an exact permitted source host. `--landing-url` starts discovery from a known publisher page, fetching its metadata before model selection. `--source-url` skips discovery to isolate extraction against an already retrieved PDF; its evidence explicitly records that discovery was not exercised in that run. The script checks the model ID, downloads the actual PDF, extracts up to the first five pages (`--pages 1` isolates the front page), and applies the same quote checks as production research. A successful extraction probe is not evidence of a successful end-to-end search run or a citation approval.


The [earlier live pilot](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/dartmouth-live-pilot.md) exposed an invented ellipsis and an inferred series title. The [follow-up benchmark](../verification/benchmark/README.md) (September 10, 2026) records source-passage extraction and a complete known publisher-page → PDF → Qwen evidence run, with all quotations passing. Its 60 offline cases across 30 real entries test documentary metadata comparisons, not 30 independent PDF reviews or model accuracy. The ten-entry expanded Crossref pilot accepted no additional entries. Broad-batch reliability and automatic PDF adjudication remain unestablished; all model findings stay `needs_review`. The September 2026 research waves were a separate process (research agents following the protocol and brief kept in the archive repository, with independent checks and user decisions); their evidence reached the library only through the [research route](#research-route).

## Catalogue verification for books

`verify --auto-review` also checks unresolved books without supplied DOIs against
the Library of Congress SRU catalogue. The first supported cases are printed,
editions with complete personal-author bylines, explicit publication years and unambiguous MARC
publication statements. The checker compares titles and subtitles, author names,
years, publishers, supplied ISBNs, addresses, editions, and all other supplied
fields; unsupported fields remain blockers. It rejects print reproductions,
ambiguous or truncated searches, unsupported creator roles, and unparseable competing
records. A different edition is not a substitute for the cited one.

Personal-name headings alone do not establish authorship: the complete
transcribed responsibility statement must confirm every author in order.
Editors, translators, analytical entries, related-work headings, incomplete
bylines such as “et al.”, and additional responsibilities remain unresolved.
The first publication place can use its explicit MARC jurisdiction code to
compare documented state abbreviations; a code never supplies a missing city,
overrides a contradictory state, or applies to a different place in the list.

Catalogue requests run serially at a minimum 3.1-second interval. Successful
responses retain the complete search XML, its hash, retrieval time, query, and
individual edition records. Errors are not negative-cached. An accepted record
uses its MARC identity rather than a guessed DOI. Portable snapshots retain this
evidence, and offline reassessment reparses it rather than trusting match flags.
The same raw-entry fingerprint policy applies: key-only renames reuse the result;
every other edit requires a new assessment, with HTTP responses reusable when the
query has not changed. DOI notices for rejected article search alternatives do
not alter a verified book edition that has no supplied DOI.

The parser follows the LOC documentation for [MARC book form codes](https://www.loc.gov/marc/bibliographic/bd008b.html),
[title statements](https://www.loc.gov/marc/bibliographic/bd245.html), and
[publication statements](https://www.loc.gov/marc/bibliographic/bd260.html),
[personal-name added entries](https://www.loc.gov/marc/bibliographic/bd700.html),
and [coded publication places](https://www.loc.gov/marc/bibliographic/bd008a.html).


Catalogue byline parsing recognizes literal `by` / `[by]` responsibility prefixes.
An explicitly recorded compound family name is grouped only when its complete
text also ends the corresponding transcribed name; the complete given names,
surname, order, and count must still agree. A terminal spaced colon in MARC
020$a is treated as the documented ISBD separator before availability terms,
not part of the ISBN. Uncertain identifiers and extra trailing text stay unresolved.


When a complete title/author catalogue search returns multiple editions or is
truncated, catalogue policy 5 makes one cached refinement using the cited year.
The LOC date index retains legacy copyright prefixes, so the query includes
both the literal year and `c`-prefixed year. This is discovery only: every
returned edition still needs matching MARC 008 and transcribed dates, byline,
complete title, publisher, and supplied fields. An empty refinement keeps the
broader evidence, and no year is inferred from the search filter. Portable
reviews accept only the exact ordinary or year-refined query derived from the
current citation. Explicit edition numbers compare across standard numeric and
English ordinal spellings; a missing or qualified edition is not inferred.

### Local PDF discovery

To index a user-provided paper folder without changing it:

```sh
.venv/bin/python bibcheck/local_library.py "/path/to/Papers" --bibliography cdl.bib
```

The default output is ignored `.bibcheck/local-library/`. Each PDF is hashed;
unchanged content reuses its first-three-page text even after a filename change.
Edited content gets a new object, deleted files leave the current inventory, and
changed-during-extraction files are held. `--retry-errors` retries unreadable
text extraction. OCR is not inferred from a filename or supplied by a model.

`candidates.json` binds discovery leads to the current entry fingerprint and
records the PDF hash and pages containing title/DOI mentions. Its status is
always `candidate_only`: filename matches, cited references, preprints and
conference versions do not establish publication identity. It neither writes
to the verification database nor grants approvals. Source checks and any
corroborated corrections still use the normal verification pipeline.

For PDFs whose ordinary extraction failed, an optional local OCR pass uses
Poppler and Tesseract:

```sh
.venv/bin/python bibcheck/local_ocr.py --bibliography cdl.bib
```

It reads the existing index and writes to ignored `.bibcheck/local-library-ocr/`.
The cache includes the complete PDF hash, extraction settings and installed tool
versions. Only the first three pages are rendered; unchanged files reuse the
result, while changed files must first be reindexed. Errors are cached until
`--retry-errors` is requested. Neither the source library nor the ordinary index
is modified. OCR candidates remain unverified: inspect page images before using
them to propose corrections, then recheck edited entries through the normal
metadata verifier. OCR can misread even an otherwise legible page range.

### Missing PubMed issue numbers

When print-year ambiguity is Crossref's only blocker, the resolver may retain
its independently matching issue number if the linked MED record omits the
issue field entirely. This requires the same DOI and overlapping ISSNs plus
complete agreement on title, ordered byline, print year, journal, volume and
page range. A present-but-empty issue or any contradictory issue remains a
blocker. Other unresolved Crossref fields cannot use this exception.

The accepted evidence labels the issue as Crossref evidence and the year as
PubMed evidence. No issue is inserted into raw MED data. Reassessment rebuilds
these judgments from raw records; content edits invalidate the old result,
while a cite-key-only rename reuses it. Resolver 25 applied this rule to three
existing records after published-source spot checks.


### Cognitive Brain Research names and historical formatting

Resolver 26 recognizes only the enumerated full and short Cognitive Brain
Research titles documented by [NLM 9214304](https://www.ncbi.nlm.nih.gov/nlmcatalog/9214304).
The section name remains mandatory: Brain Research, Brain Research Reviews and
Brain Research Bulletin are distinct. This comparison does not relax author,
publication-coordinate, notice or version checks.

Formatting now preserves `Brain Research Reviews` rather than forcing the
1989–2005 prefixed NLM title onto later articles. The two Reviews titles are
not global aliases. A bibliography correction still requires the existing
paired-source journal proposal and a new entry fingerprint. Tests exercise real
records, distinct neighboring journals, external holds, exact cache restoration,
cite-key reuse, and invalidation after a page edit.

Resolver 27 adds exact documented journal labels: the registered-trademark
spelling of *Foundations and Trends in Machine Learning*, and the full
Royal Society B Biological Sciences variants used by Crossref, NLM and the
repository formatter. It does not strip symbols from arbitrary journal names
or paper titles, remove section/subtitle words, infer matching authors, or
disregard competing publication versions. In particular, WainJord08 still
requires its printed journal DOI to distinguish the separately indexed
monograph. See the [source audit](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/completion-2026-09-15/documented-journals-audit.json).

Catalogue policy 6 adds a discovery-only fallback for combining accents. If the
ordinary complete-title/first-surname search returns zero records, a second query
omits combining accents; year refinement uses the same query form if needed.
Both query forms have separate response-cache identities. Retrieved titles and
author names retain their original accents and must pass the same complete
edition checks. A real LC search for Buzsáki demonstrated the indexing mismatch;
a six-book live pilot recovered one fully matching Gärdenfors edition. Incomplete
author headings, wrong editions and conflicting publishers remain unresolved.

### Repository preprints

`verify --auto-review` now has a separate bioRxiv preprint route. It binds the
repository's complete version history to the exact version-page HTML head and
Crossref's posted-content/preprint DOI record. Title, complete ordered authors,
posting year, repository, identifiers and every other supplied bibliographic
field must agree. The version page's actual `citation_date` is used; its generic
January 1 `citation_publication_date` placeholder is not a posting date. A later
journal DOI remains a relationship, never a replacement for the cited preprint.

Existing bioRxiv citations may carry the repository identifier in `doi`, `volume`
or `pages`; this route validates those values as repository identifiers, rather
than pretending they are journal volumes or printed page ranges. Conflicting
identifiers, unsupported fields, source author conflicts and unpinned multiple
versions remain unresolved. Withdrawal or correction evidence in any retrieved
version blocks approval even when an earlier version is explicitly cited. Raw
repository history, version HTML and registry records travel with the snapshot;
known withdrawal evidence survives subsequent entry edits and fresh restores.
All source retrieval is paced and cached. Key-only renames reuse approval; other
edits invalidate it. This route currently covers bioRxiv, not arXiv or PsyArXiv.

Provider documentation: [bioRxiv API](https://api.biorxiv.org/) and
[bioRxiv withdrawal policy](https://connect.biorxiv.org/news/2023/08/15/preprint_withdrawals).

### arXiv repository verification

`verify --auto-review` also checks explicitly cited arXiv articles through
`bibcheck/arxiv_review.py`. It compares complete ordered author lists, titles,
identifiers, dates and version histories across the Atom API, repository HTML
head/history and DataCite's DOI record. Legacy identifiers in volume/pages and
split volume/number fields are checked as repository identifiers. Unsupported
fields and malformed or conflicting sources remain unresolved.

An unversioned arXiv identifier denotes the latest version, as documented by
[arXiv](https://info.arxiv.org/help/arxiv_identifier.html). Its title and byline
must match that version; the approval records the exact version inspected.
The citation year must match DataCite's publication year, corroborated by the
first-submission timestamp. An explicit `vN` citation instead requires its own
version-specific API and HTML sources and uses that version's submission year.
Latest and selected histories must agree. Repository dates are distinct from
later conference/journal publication dates.

Complete DataCite submitted-version timestamps must match the page history and
API dates. Current registry metadata corroborates the latest version and never
supplies missing names or titles for an older selected version. The live pilot
found a real surname typo in an earlier version, covered by a regression test.
Withdrawals, retractions, unsupported relationships and retained DOI-linked
notice evidence block approval, including when an older version is explicitly
cited. Negative controls stay outside the bibliography. Known notices also
survive edits to entries whose identifiers are in legacy volume/pages fields.

The dated `arxiv_collect.py` runner collects a frozen batch in a separate cache;
`arxiv_verify.py` applies the production route using those saved sources and
checks an unchanged, zero-request/zero-write repeat. Raw sources are embedded in
portable snapshots and approvals are reconstructed during import. Direct PDF
source conflicts can be attached as explicit holds; PDF or LLM output does not
independently approve an entry.

## Phase 0 rules and new evidence modules (2026-09-22)

Resolver 28 scopes correction/retraction notices, coordinate conflicts and PubMed
suffix conflicts to the cited work's own DOI (or a DOI whose title matches), treats
byte-identical Crossref records as one, applies the print-year rule above, treats
clean APA `10.1037//` twins as one work, stops chapter/preprint/report rivals and
contradicting journal rivals from creating ambiguity, and adds four documented
ISSN-pinned journal-name variants. Correction proposals may come from a single
authoritative source (Crossref or PubMed) when identity is established; see
[phase0-2026-09-22/README.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/phase0-2026-09-22/README.md) in the archive repository. Catalogue policy 7
widens the Library of Congress record parser
([catalogue-phase0-2026-09-22/README.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/catalogue-phase0-2026-09-22/README.md)).
`bibcheck/pdf_evidence.py` is a position-aware local-PDF verifier with a
subtle-error benchmark (`verification/pdf-benchmark/README.md`); it is **not** wired
into any approval path.

## Repository and registry routes (2026-09-25)

Four further `verify --auto-review` routes cover works Crossref does not describe. Each
has its own module, policy constant, `run_*` function and registered approval
validator; design, meeting keys and the 2026-09-25 yield are in
[routes-2026-09-25/README.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/routes-2026-09-25/README.md)
in the archive repository.

|Route|Module|Source|
|-|-|-|
|PsyArXiv|`bibcheck/osf_review.py`|OSF API v2: version list, bibliographic contributors, primary-file revisions|
|Software and data|`bibcheck/datacite_review.py`|DataCite REST API (`/dois/<doi>`, title search)|
|ACL Anthology|`bibcheck/acl_review.py`|`https://aclanthology.org/<id>.bib`; OpenAlex only nominates identifiers|
|SfN abstracts|`bibcheck/sfn_abstracts.py`|the abstractsonline.com meeting planner (2009-2015 meeting keys confirmed)|

A route can verify an entry, propose source-backed field values, flag a published
version for replacement, or hold the entry. Only PsyArXiv is supported among OSF
preprint servers (`osf_review.PROVIDERS`). A preprint is compared with its latest
version, and when OSF lists a published article DOI the entry is classed `replacement`
and never verifies. Software titles take the house form `{Owner}/repo: {version}` and
every creator is compared in order. The SfN route can confirm a meeting abstract, but
under the lab's rules conference abstracts are dropped from `cdl.bib` (see
[Decision rules](#decision-rules-for-what-the-library-contains)).

## Correction, erratum and retraction notices

A DOI-linked notice (from PubMed, JATS front matter, or a Crossref `update-to` /
`updated-by` relation), a PubMed author-suffix conflict, or a coordinate conflict holds
a machine approval (`preprint_review.context_issues`, `Cache.retain_notices`). Only
`human_verified` is exempt. The evidence is scoped to the cited work's own DOI
(resolver 28) and survives edits and restores, as described under
[Known correction notices](#known-correction-notices).

The notices that held entries in September 2026 were read and classified by hand in
[resolution-2026-09-27/NOTICES.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/resolution-2026-09-27/NOTICES.md)
in the archive repository (`notices-classified.json`, one row per notice with its URL and
quote). The research
route settles a notice only through that classification
(`research_route.notice_adjudication`):

- a retraction or expression of concern is never approved; the user decides;
- a content-only erratum, a metadata correction the entry already carries, a same-DOI
  new version, a notice that is itself the cited work, and a record that is no notice or
  belongs to another work are settled, and the approval carries a `notice_*` flag;
- a coordinate conflict is settled when the entry carries the Crossref value (round-1
  rule: the publisher/Crossref record wins);
- a notice nobody could read (paywall, CAPTCHA, no notice DOI) is treated as an erratum
  only when the classifier's notes record that Crossref and Europe PMC show no retraction
  or expression of concern; the approval is flagged `notice_unread`.

A notice learned after approval reopens the entry. The 2026-09-28 printed-paper rule
applies here: a correction is a reason to doubt the registry, so when neither the
printed article nor the notice could be read, the entry was dropped as ambiguous
(ChanEtal12). A correction that withdraws a paper's headline claim was reported to the
user, who dropped the entry (GrilEtal06b).

## Research route

`bibcheck/research_route.py` covers the entries that the September 2026 research waves
verified field by field. Their saved results in `verification/baseline.jsonl.gz` have
status `metadata_verified` and `accepted_source = research-evidence`; each records, for
every field, the researched value, the quotation, the source URL and the sha256 of the
fetched page. The research files, the route's design notes and the
`crossref research-approve` command that built these results from them are in the
archive repository ([research-route-2026-09-27/README.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/research-route-2026-09-27/README.md)).
The command is not on this branch, because it read those research files; neither is
the code that read them or its tests (tests/fixtures/research_route/). What stays in
`bibcheck/research_route.py` is the re-check below and everything it calls.

An entry was approved only when:

1. a research row (or a resolution decision) settled it, nothing marked it for removal,
   and an identity quote was found in its saved source body;
2. every field of the entry except `ID` and `ENTRYTYPE` equalled the latest researched
   value after house normalization, and that value was supported by a quote found in
   the saved body. No field was exempt;
3. the entry type matched the evidence;
4. no DOI-linked notice, suffix or coordinate conflict was open, unless the notice
   classification above settled it.

Quotes read in a real browser or transcribed from an image-only scan count only for
resolution and manual rows whose notes say so, and are flagged `browser_or_scan`.

`valid_research_approval` is registered as an approval validator, so `crossref restore`
re-checks every research approval offline from the snapshot alone: the saved record must
be complete and self-consistent, and it must re-derive to the same approval with the
research validator's quote matching (`bibcheck/research_quotes.py`) and the post-check's
house normalisers (`bibcheck/research_forms.py`), both copied unchanged from the research
tools. Where a local `.bibcheck/research-pilot/` body cache exists, a quote is searched
again in its body; otherwise the recorded quote result is used. Editing an entry sends it
back through ordinary verification. `tests/test_research_route.py` runs the re-check on 14
frozen baseline rows (`tests/fixtures/research_approvals/`, every flag and notice class),
with negative controls: a changed quote, value, record or body, a missing notice class, or a
retraction on the cited DOI is rejected.

This route is separate from the optional LLM adapter below: `crossref research` and
`research-batch` save evidence for review and never approve.

## Continuous integration

`.github/workflows/citation-check.yml` (workflow name "Citation verification") runs
`verification/check_ci.py` on pull requests to `master`, pushes to `master`, and manual
dispatch. All jobs share one serial concurrency group, and `CROSSREF_MAILTO` comes from
the repository's Actions variable.

- On a pull request or push, it writes the base revision's `cdl.bib` to
  `.bibcheck/base.bib`, restores the base revision's `verification/baseline.jsonl.gz`
  (never the snapshot in the pull request), and runs
  `crossref verify cdl.bib --auto-review --against .bibcheck/base.bib`. Only new or
  edited content is gated; key-only renames are excluded.
- A push whose base revision is not in the history (a force-push, rewritten history, or
  a new branch) has nothing to compare against. Its content is already merged, so the job
  restores the pushed commit's own `verification/baseline.jsonl.gz` and runs
  `crossref status cdl.bib` (offline): every entry must have an accepted result for its
  exact current text. Pull requests never take this path; one without a base is refused.
- A manual run restores the committed baseline and checks the whole library.
- The SQLite database is kept in the Actions cache, keyed by ref; a pull request can
  fall back to the `master` cache, and `master` never restores a pull-request cache. The
  report and a checkpoint snapshot are uploaded as artifacts. The cache only saves
  lookups: an approval in it can come only from the checker's own runs, never from a
  file in the pull request.
- Exit status: `0` when every selected entry is verified, `1` otherwise, `2` for a
  configuration or provider error.

Because approvals are trusted only from the base branch, a pull request that adds a
`human_verified` approval to `baseline.jsonl.gz` still fails its own check for that
entry; a maintainer merges it after checking the approval. The job runs the pull
request's own code, so this guarantee assumes the checker itself is unchanged; review any
change under `bibcheck/` or `verification/check_ci.py` separately.

The separate `autocheck` workflow runs `bibcheck/test.py` (the formatting check of
`cdl.bib`) and `pytest tests` on Python 3.11.
