# Citation verification design

This is the design reference for `cdlbib crossref` and the `verify` gate. The
[README](../README.md) covers everyday use. The dated folders in
[verification/](../verification/README.md) record how the library was brought to its
current state; sections below that describe a dated pilot or measurement say so.

The command downloads a managed library when no bibliography was named or found.
Run `cdlbib where` to find it; see [Installation](../README.md#installation) for
locations, lookup order and updates. An existing clone is used without being updated
by the tool. Explicit bibliography arguments select that file instead.

## Current state

As of September 30, 2026, `cdlbib crossref status cdl.bib` (after restoring
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

`auto_review.resolver_version` independently versions additive resolver improvements. A new resolver revision reconsiders unresolved saved evidence once and preserves completed provider-lookups; it does not recheck current accepted entries. Revision 2 added exact PNAS and Journal of Neuroscience title variants. Revision 3 adds narrowly bounded corporate publisher names, corroborated issue labels, and explicit final-article DOI handling; see the [resolution audit](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/resolution-2026-09-15/README.md). Revision 4 separates explicitly dotted initials such as `A.A.` into the same tokens as `A A`; it does not infer missing names or expand undotted acronyms. Newly eligible secondary DOI targets reopen the relevant checkpoint while retaining already-queried DOIs. Revision 31 compares an `editor` field with the record's editors ([Editors](#editors-resolvers-31-and-32)); revision 32 compares a chapter's editors with the book's own record. A stricter acceptance-policy change must still use the separate policy invalidation mechanism.

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

`crossref revoke KEY --reason WHY [--fingerprint FP ...]` withdraws a human
approval that should not stand, for example one recorded in someone's name without their
decision. By default it revokes every human approval recorded for the key, including ones on
older text that later edits made lapse; `--fingerprint` restricts it to specific texts. For
each approval it appends one row to `verification/revocations.jsonl` and to the database's
`revocations` table. The row records the key, the approved fingerprint, the approval
(reviewer, source, note, time) and its digest, `revoked_at`, `revoked_by` (the GitHub login
of the `gh` CLI) and the reason. The
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

### Sharing an approval: the approvals ledger

`verification/approvals.jsonl` is the counterpart of `revocations.jsonl` for approvals. It
is written by `cdlbib send` (`api.send`, which the terminal and web interfaces call through
`api.send_checked`) and by nothing else; `approve` writes only to the database.

Writing. Before `send` decides whether there is anything to send, `api.approvals_waiting`
lists the rows to add: one for each entry whose stored result in the local database is a
current `human_verified` result for exactly the entry's text, with a `human_review` that
has a non-blank reviewer, source, note and `github_login`, that is not revoked, and whose
(fingerprint, digest) pair is not in the file yet. When nobody is logged in, no row is
added, each waiting approval is reported as not sent for that reason, and `send` goes on in
its usual order (the gate, then the refusal for the missing login; an approval alone is the
"no changes" refusal with those lines). When such a row exists, `send` asks
`gh` who is logged in (`identity.current`) and keeps only the rows recorded under that user:
the same `github_id` when the review has an integer one, else the same login ignoring case.
The others, and stored approvals under a login that are not valid rows, are returned as
`unsent` (`{"key", "login", "why"}`); `progress` receives `approval of KEY not sent: WHY`
for each, and the refusal when nothing else is to be sent lists them. An approval whose
`human_review` names no GitHub login is in neither list. `record_approval` refuses a
reviewer, source or note over the row limits, and a review with a `github_login` that would
not be a valid row, so an approval made with `approve` can always be written. It also
refuses a review whose source and note equal a revoked approval's of the same text after
white space is collapsed and case folded, the rule `shared_revoked` applies to rows. The
library state lists `approvals`, `unsent_approvals` and the `login` they were told apart by;
it asks `gh` only with `refresh`, and otherwise uses the user `gh` last named in the
process (`api.known_identity`), or none. The rows are appended before the gate
(`verification.append_approvals`: one line each, `json.dumps` with sorted keys and no
spaces; earlier lines are not touched), and `progress` receives a line for each. The file
is under `verification/`, so it is committed and pushed with the change, and it alone is a
change to send. Before the file is touched, a record of the rows about to be added
(checksums of the file before and after, the added bytes, git's index entry for the file) is
kept durably in `.bibcheck/approval-send/pending.json` (`writer.keep_record`). The file is
read and replaced whole by name within its folder held open (`writer._Folder`, `O_NOFOLLOW`):
a link in the place of `verification/` or of the file is refused before anything is read,
and there is no half-written line. (That holds for the library's folder and what is in it.
The folders above the library, the path the library was opened by, are taken as the
user's own and are not walked link by link.)

**Other programs writing the library's files while cdlbib writes them.** cdlbib's own
commands take a lock; an editor, a sync service or a script does not. What then holds
(`src/cdlbib/writer.py` says how):

- Nothing another program wrote into `cdl.bib`, `verification/key-renames.json` or
  `verification/approvals.jsonl` is ever deleted by cdlbib. It is either in the library, or
  in the copy kept for the write that replaced the file (`.bibcheck/edits/<time>-<file name>`;
  the copies of the newest 20 writes are kept), or in the folder of a write that had to keep
  something (`.bibcheck/kept/<time>-<random>/`), and then the message of that write names
  the path. cdlbib never removes anything from `.bibcheck/kept`.
- A program that saves by rename, as editors do: a save made while cdlbib writes makes
  cdlbib's write refuse ("changed while applying; nothing was written"), and stays.
- A program that writes the file in place, or keeps it open: what it writes before cdlbib's
  exchange makes the write refuse; what it writes afterwards through a descriptor it still
  holds goes into the copy in `.bibcheck/edits`, which is the file it has open, not into the
  library.
- Not guaranteed: which of two saves made at the same moment ends up as the library file.
  For an instant cdlbib's new text stands under the file's name before it is confirmed; a
  program that reads the file in that instant and then saves what it read replaces, itself,
  whatever another program saved in between. In the managed library (which keeps no copies
  beside itself) a write through a descriptor still held on a replaced file is lost.
- When a write cannot tell what state a file is in, it says so, keeps its record
  (`.bibcheck/edits/write-in-progress.json`), and the next command that writes settles it. `api.settle_approval_send` settles the record: when the
send raises (the append and the progress callbacks are inside the protected block), when it
succeeds, and whenever the library's lock is taken (`library.transaction`), which settles a
send that was killed. If the file holds exactly what the send left and no commit holds it,
the file is put back to the bytes it had (removed when it did not exist) and the index
entry to what it was; if a commit holds it, only the record is dropped; if anything else
changed the file, it is not written to, and the refusal (or the settled line) says that it
was not put back and names the rows. The approvals stay in the database.

Before anything is written, `send` compares the working tree's file with the copy in the
commit the checkout is on (`_outgoing_ledger`): the committed bytes must still be there,
first, and every added line must be a valid row. gh is asked who is logged in once, when a
row waits or the file has uncommitted rows; those rows, the rows the send adds, and (after
the upstream base is fetched) every row the upstream does not have must have been recorded
under that user (`_require_own`), and gh is asked again after the gate and before
publication (`_still`): another answer, or none, refuses the send. `api.approvals_note` adds to the pull
request's text the entries whose current approval is a row that the upstream base's copy of
the file does not hold, whether or not the entry differs from the reference.

A row:

|Field|Content|
|-|-|
|`key`|The entry's key when the row was written. Informational: matching is by fingerprint.|
|`fingerprint`|The content fingerprint of the approved text.|
|`human_review`|The stored record: `reviewer`, `github_login`, `github_id`, `source`, `note`.|
|`approval_digest`|`approval_digest(human_review)`, the identity revocations use.|
|`approved_at`|The stored result's `checked_at`. It is beside `human_review`, not inside it, because the digest is a hash of `human_review`.|
|`policy`|The `POLICY` the approval was stored under.|

Reading. `Cache.get` returns the stored result when it is a human approval. Otherwise it
looks for rows with the entry's fingerprint (`Cache.shared_approval`) and returns a
`human_verified` view built from the newest row whose `policy` is the current `POLICY` and
that no revocation matches (`shared_revoked`, below). The view keeps the stored result's evidence, takes `human_review` from
the row and `checked_at` from `approved_at`, and is not written to the database
(`Cache.stored` is the result without the ledger). Every command that reads results through
`Cache.get` therefore sees the approval, with no `restore`. A row is treated as an approval
stored in the database is: there, the newest stored result for the text is the current one,
whatever its status. So a result stored in the reader's database for the same text with a
`checked_at` strictly later than the row's `approved_at` outranks the row (any stored
status: `needs_review`, `provider_error`, `metadata_verified`), and the entry has that
result's status. The times are compared as parsed instants with a zone, not as text. A
stored result whose `checked_at` is missing or cannot be read counts as later than any row,
so that a failed check is not hidden for want of its date. With nothing stored, or a
stored result no later than the approval, the row counts. A newer row, or a new `approve`,
recorded after that result counts again. Tests:
`test_a_result_stored_after_the_approval_outranks_a_ledger_row_as_it_does_a_local_approval`
and the two after it in `tests/test_approval_ledger.py`.

Validation. `scan_approval_ledger` reads the file and returns the valid rows and a list of
problems; it does not raise for anything the file holds. A line is ignored, and reported
with its line number, when it is longer than 32 KiB (32,768 bytes), is not UTF-8 JSON, names a field
twice, or is not a valid row (`shared_approval_problem`): exactly the six fields; a `v2:`
fingerprint; a `human_review` with non-blank text for `reviewer` (at most 200 characters),
`github_login` (a GitHub login), `source` (4,000) and `note` (8,000), an integer
`github_id` when present, and no other field; an `approval_digest` equal to the digest
computed from `human_review` (the stored digest is never used for anything else); an
`approved_at` that is a time with a zone and not more than five minutes ahead of the
reader's clock (`approved_at` is typed text; a row dated in the future is ignored and
reported, is never written, and `send` refuses a ledger that holds a new one); a `policy`; and, as written (compact JSON plus the
newline), at most 32,768 bytes. `record_approval` applies the same byte limit to the row an
approval would become, and refuses one that would take the ledger over 8 MiB;
`approval_lines` checks both again when a send adds rows. A file larger than 8 MiB, or one that cannot be
read, is ignored whole and reported. `api.approval_problems`, `crossref status` (standard
error), the progress lines of `send` and the notes of the library state show the problems.
`append_approvals` refuses to write a row that is not valid, and `approvals_to_send` does
not list an approval whose row would not be.

Which copy is read (the trust model). A row is text that anyone can type, so what a typed
row can do depends on which copy of the file a command reads:

|Reader|Copy of `approvals.jsonl` read|
|-|-|
|Pull request check, and push check with a base (`check_ci.py`)|The base revision's, passed as `crossref verify --trusted-approvals FILE`.|
|The citation gate of `cdlbib verify` and `cdlbib send` when it compares with a reference (`citation_gate`)|The reference's (`reference_approvals`): for `github`, `master`'s file, downloaded to `.bibcheck/reference-approvals.jsonl` (empty when `master` has none); for a reference file, an empty one. This holds whichever entries are checked (new and edited, `--all`, or chosen keys); when all entries or chosen keys are checked and `master`'s file cannot be downloaded, no row counts and the gate prints a line saying so. No environment variable names a ledger.|
|`crossref status`, `crossref verify` run by hand, the library views, `restore`, `snapshot`, a push check without a base, a manual workflow run|The file beside the revocation ledger the cache was opened with: the checkout's own.|
|A cache opened without a ledger|None.|

In the first two rows a row counts only once it is on the branch the change is compared
with, so a row cannot approve an entry in the check or the gate of the change that adds
it. In the third, the working tree's file has the trust of the checkout itself, which is
what `crossref restore` of a snapshot file, or an `approve` in the local database, already
has: none of them is read by the pull request check. An approval the sender recorded with
`approve` is in the sender's database and counts in the sender's own gate, as before.

Rows are validated when they enter the ledger, not only when they are read. `send` writes
only rows that are valid at that moment and refuses a ledger whose uncommitted lines are not
(`ledger_additions`). The pull request check runs `crossref check-ledger --base FILE` first:
it fails when a line the base revision holds was removed or changed, or when an added line
is not, at the time of the run, a valid row under the current `POLICY` whose fingerprint is
that of an entry of the same commit's `cdl.bib` and whose `key` is that entry's key (any of
them, where the same text stands under several keys). So nothing can be merged today and
begin to count later: not a row dated ahead of the clock, not a row for another policy, not
a row for a text that no entry has yet. `send` applies the same function to the working
tree. Lines the base already holds are not checked again: a row whose entry was edited or
removed since no longer matches any entry and is not an error for later changes. A reader still validates
every row each time, and a row typed into a working tree is subject to the reader's clock
there.

One revocation rule (`approval_revoked`, asked through `Cache.revoked`). Every reader of
approvals asks it, over every revocation the cache knows (`Cache.revocations`: the
database's `revocations` table, which also receives the rows of a restored snapshot and of
`--trusted-revocations`, and the revocation ledger file): `Cache.stored` for an approval in
the database, `Cache.shared_approval` for a ledger row, `import_snapshot` for a restored
result, and `record_approval` for a review about to be recorded. `current_results`,
`status`, `snapshot`, the library views, `approvals_note` and `approvals_waiting` read
through `Cache.get`/`Cache.stored`. A revocation revokes an approval with the same
fingerprint when any of these holds: the digest computed from its `human_review` is
one the revocation names (`revoked_digests`); its time (a row's `approved_at`, a stored
result's `checked_at`) is not after `revoked_at`, compared as instants, or cannot be read;
or its `source` and `note`, with white space collapsed and case folded,
equal those of the approval the revocation carries. The third rule means a copy of a revoked
review with other spacing, another time, another reviewer or another `github_id` is not a
new decision. `approved_at` is typed text like the rest of the row, so a row with a new note
and a later time counts as a new decision, as a new `approve` with a new note does.

`record_revocation` also finds approvals that exist only as ledger rows (rows
with the key, or with the entry's current fingerprint), so `crossref revoke` works on a
computer whose database never stored the approval. The approvals ledger is not edited; the
revocation row is what makes the approval stop counting. `restore` stores a snapshot's
result for a text even when a ledger row approves it. `snapshot` exports current results,
so an approval read from the ledger is written into a new baseline as `human_verified`.

Tests: `tests/test_approval_ledger.py`, and
`test_a_pull_request_reads_the_approvals_ledger_of_its_base_only` in `tests/test_check_ci.py`.

## Operational limits

- Crossref deposits can be incomplete or incorrect. A metadata match is not independent corroboration from the PDF.
- The Crossref comparison supports `article`, `inproceedings`, `book`, and `incollection` only when the Crossref type agrees. Other types (software and data in DataCite, repository preprints, catalogue books) need one of the other routes, and a field no route verifies blocks approval (`no deterministic verifier for this field`).
- Crossref keeps a book's editors on the book's record. Few chapter records repeat them (79 of the 6,573 chapter records among the saved candidates of the 2026-09-30 baseline; 63 of 2,364 proceedings-paper records, nearly all of them SPIE's), so an `editor` field is seldom verified from Crossref ([Editors](#editors-resolvers-31-and-32)).
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

The included `src/cdlbib/openai_research_adapter.py` uses the [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [web search](https://developers.openai.com/api/docs/guides/tools-web-search), and [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Set `OPENAI_API_KEY` and `BIBCHECK_RESEARCH_MODEL` explicitly. The model must support these capabilities. Discovery must actually execute a completed web-search call; extraction receives the downloaded PDF page text and has no tools. Refusals, incomplete responses, duplicate fields, or missing page quotes fail closed. Usage and source traces are retained with successful evidence. The key is never printed or written into a report, and API calls use `store=false`.

Python adapters are invoked with the current Python interpreter; other executable adapters retain the original subprocess contract. `research-batch` defaults to ten unresolved entries, caps a single invocation at 100, checkpoints success/failure, skips unchanged prior attempts, and stops after three consecutive failures. `--retry-failed` deliberately revisits failures. Edits invalidate research findings through the same exact-entry fingerprints. Ordinary `verify`, `auto-review`, and `fulltext-review` never invoke a commercial provider.

OpenAI request limits are four web-tool calls per discovery and 4,000 output tokens per model response, with at most 100 KB of input per phase. These bounds do not implement a dollar cap; the user must configure provider spending limits/model pricing for a large batch. The adapter has offline protocol tests; live provider/model availability must be validated separately before scaling. LLM research saves evidence and proposed field interpretations, not `human_verified` status. Human adjudication is reserved for conflicts and inaccessible/ambiguous sources that cannot be resolved by deterministic source checks.


## Dartmouth Chat and custom search

`src/cdlbib/dartmouth_research_adapter.py` uses Dartmouth's documented `/api/chat/completions` endpoint and `DARTMOUTH_CHAT_API_KEY`. `BIBCHECK_RESEARCH_MODEL` defaults to `zai-org.glm-5.3`, live-confirmed on September 14, 2026. `--check-model` and every adapter invocation check `/api/models` for that exact ID and free eligibility; they never substitute another provider. Both **Local** and **Free** tags qualify, but an explicit nonzero or malformed price overrides the tag and rejects inference. Run `python -m cdlbib.dartmouth_models .bibcheck/dartmouth-models.json` to refresh a sanitized catalog without private upstream metadata. See [Dartmouth model tags](https://rc.dartmouth.edu/ai/online-resources/understanding-tags/), [API usage](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/basic_usage/) and [model discovery](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/model_list/).

The full GLM 5.3 model is the selected free text model; Flash is a separate faster multimodal option. The [full model card](https://huggingface.co/zai-org/GLM-5.3) describes text-only input despite Dartmouth's reported vision capability. Requests use maximum reasoning, temperature 1, top-p 0.95, clear thinking history, a 16,000-token output cap, and a 240-second read timeout. Model benchmarks informed selection; the repository's representative source audit tests actual extraction behavior separately. The adapter was first built and piloted with `qwen.qwen3.5-122b`, which it still supports with its own settings (below); the live results in this section date from that Qwen configuration, not the GLM default.

The model uses a client-side JSON action loop, so native function calling or hosted search support is not required. It can request `web_search(query)`, see the results, revise its query, select a retrieved PDF source by index, or report that the source remains unresolved. Only these actions are interpreted; no shell commands, arbitrary functions, or model-supplied URLs execute. Tool data is explicitly untrusted. Allowed hosts govern page and PDF retrieval, including redirects. URLs from registry records and publisher `citation_pdf_url` metadata can also supply candidates. A link is a discovery clue, not evidence that the publication/version matches.

`src/cdlbib/search_tools.py` provides two explicitly selected free backends:

- `BIBCHECK_SEARCH_BACKEND=europepmc` (default): the [Europe PMC REST API](https://europepmc.org/RestfulWebService), including full-text PDF links when supplied by its records. It covers scholarly literature, not general web content.
- `BIBCHECK_SEARCH_BACKEND=duckduckgo`: a parser for DuckDuckGo's public HTML search interface. This is experimental, not an official search-results API or the Instant Answer API. Challenges, throttling, and unrecognized pages fail without proxy rotation, challenge bypass, or automatic retry. There is no silent provider fallback.

Each search returns up to five results. Successful queries, including recognized empty results, are cached for seven days in `.bibcheck/search.sqlite3`; change its location with `BIBCHECK_SEARCH_CACHE`. Uncached queries wait three seconds, source requests wait one second, and Dartmouth calls wait two seconds. Runs are serial within the existing research batch lock; the Actions workflow additionally serializes its jobs. Do not launch independent research processes with different verification databases to evade pacing. Cached discovery results never change a verification status or defeat exact-entry invalidation.

Per entry, discovery permits at most three distinct searches, four model responses, three landing-page lookups (each with at most four requests including redirects), and twenty candidate PDFs. Extraction adds one model response. Each model request caps input data at 100 KB; output is capped at 16,000 tokens for GLM 5.3 and 4,000 tokens for other models. The adapter timeout is 600 seconds per phase to accommodate this bounded loop. GLM 5.3 responses have a 240-second read timeout. For other models, discovery responses have a 90-second read timeout and PDF extraction allows 240 seconds, after a live Qwen extraction exceeded the original 90-second limit. Refused, truncated, malformed, or unsupported responses fail closed. These limits bound requests, not model accuracy. JSON is requested in the prompt and checked locally; strict provider JSON-schema support is not assumed. Optional Markdown fences are removed without changing JSON values. Duplicate JSON keys, trailing prose, multiple objects, and invalid field evidence are rejected. For `qwen.qwen3.5-122b`, requests use Qwen’s documented direct-response settings (`chat_template_kwargs.enable_thinking=false`, temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5). These settings are based on the [official Qwen model guide](https://huggingface.co/Qwen/Qwen3.5-122B-A10B); gateway support must be validated live and the settings are not an accuracy guarantee.

Publisher landing-page discovery reads `citation_*` metadata only from HTML head tags, excluding body/reference-list tags and retaining conflicting values. Its supplied PDF links become candidates; this is discovery evidence, not a new HTML acceptance rule. The model may select a retrieved publisher PDF without making a general search call. PDF selection returns only an existing source index. Up to two alternative PDF links from that same retrieved record may accompany it; links from other candidate publications cannot be substituted. Bibcheck tries at most three supplied copies after download failures and records each attempt. This does not establish that mirrors have identical publication versions. Bibcheck downloads the actual PDF and saves its hash and first five pages of extracted text. Dartmouth extraction receives numbered source passages without the input BibTeX fields. The model returns field values and passage IDs; Python copies the exact original slices and validates every page, offset, and quotation. Unknown IDs and duplicate non-author fields fail closed. Individual author selections are assembled in source order. Conservative literal checks preserve accents and subtitles and flag inferred values; BibTeX entry type always requires interpretation. Literal support does not establish field role, identity, author completeness, or publication version. Because a receipt date, a copyright notice, a preprint version stamp, an affiliation line and a reference-list entry are all literally present on the page, each field's evidence additionally carries a `role_risk` list, collected in `role_risk_fields`, naming printed roles that make the proposed value suspect: `reference_list`, `receipt_or_revision_date`, `copyright_line`, `preprint_version_stamp`, `affiliation_line`, `institution_named_as_venue` and `possible_omitted_author`. Each match also becomes an explicit uncertainty. These are pattern heuristics over the selected passages, never an approval and never a rejection; they deliberately over-flag, because a false positive withholds acceptance while a false negative would admit a wrong value. An empty `role_risk` is not evidence that the role is correct. The generic adapter contract above remains supported for other providers. Both discovery and extraction uncertainties survive in the evidence. Successful evidence includes the search queries/results, source URLs, timestamps, cache-use indicators, and model usage. Failed research attempts are checkpointed; successful search results remain cached even if later model/PDF processing fails. Neither adapter edits BibTeX or grants verification.

The manual `.github/workflows/dartmouth-research.yml` pilot consumes the GitHub repository secret, checks model availability, and defaults to three entries (maximum ten). Inputs reach commands through environment variables and argument lists, not interpolated shell code. It restores the portable baseline and caches `.bibcheck` between runs; edited entries still lose eligibility automatically. An always-run checkpoint exports a snapshot artifact, including failure records. PDFs stay in the runner/cache, not the artifact. A GitHub cache is temporary storage and can be evicted. No credentials appear in snapshots or model prompts. Existing attempts are skipped unless the explicit retry input is enabled.

Validation (September 2026, Qwen configuration): both search connectors returned real results in a September 9, 2026 probe; DuckDuckGo found the proceedings PDF and arXiv record for “Attention Is All You Need.” Live Dartmouth authentication and search actions with `qwen.qwen3.5-122b` succeeded. Testing exposed DuckDuckGo HTTP 202 challenges, a stale publisher PDF returning 404, and Europe PMC PDF throttling (429). These failures remain unresolved rather than becoming approvals. Local tests cover adaptive query revision, persistent caching, fabricated source indexes, invalid quotations, budgets, blocked redirects, and challenge handling. GitHub cannot reveal an Actions secret for local use, and a manual workflow can be dispatched only once it is on the default branch.


### Local credentials and live debugging

If `DARTMOUTH_CHAT_API_KEY` is unset, the Dartmouth adapter reads the key from the system keychain: the item `dartmouth-chat-api-key`, with your operating-system user name as the account (`keyring set dartmouth-chat-api-key "$USER"` stores it). The OpenAI adapter does the same with `OPENAI_API_KEY` and the item `openai-api-key`. The key file `.bibcheck/secrets/dartmouth_chat_api_key.txt` and `BIBCHECK_DARTMOUTH_KEY_FILE` are no longer read. The keychain read waits at most 60 seconds. On macOS, an item created with the `security` command makes macOS show an access prompt the first time Python reads it; choose "Always Allow". The environment variable takes precedence. The key must be a single nonempty token. Never include it in source files, command arguments, reports, or prompts.

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

### Books built from catalogue records

`cdlbib add` builds a `@book` from one MARC record of the same catalogue
(`cdlbib.book_build`). The request is the catalogue check's
(`catalogue_discovery.fetch_query`: the same endpoint, pacing and response cache); the
query is `bath.isbn="…"` or `bath.lccn="…"` for a standard number, and the check's own
title/author query for a title search, so the check later reads the same saved response.
The record is read by the check's grammar (`catalogue_review.parse_edition`) and each
built field is kept only when the check's comparison (`catalogue_review.compare_edition`)
accepts it for that record. The proposal's status comes from the verifier: the first
check, then `catalogue_review.review_book`, the function `run_catalogue_review` also
calls. No approval is recorded, and a written book is verified by `verify` through the
catalogue route like any other book.

| Field | Written from | Not written when |
|-|-|-|
| `title` | 245 `$a` and `$b`, through the title formatter; a capitalised word after the first is braced | the record's title has markup |
| `author` / `editor` | the people the grammar reads, as initials and surname | the byline is incomplete or corporate (the grammar then reads no record) |
| `year` | 008 date 1 (the grammar requires the transcribed date to agree) | |
| `publisher` | the transcribed publisher, through the publisher formatter; the first of two is written as a question | the check does not accept the formatted name |
| `address` | the publisher's first place; with the state's two-letter code when 008/15-17 names one of the states the check compares | the check does not accept the formatted place |
| `edition` | a numbered statement, as `2\textsuperscript{nd}` | the statement is not a number the check's edition comparison reads ("Rev. ed."). The catalogue's older "2d ed." and "3d ed." are read as the second and third edition since 2026-10-06; the entry then stays `needs_review` |

An answer to an ISBN or LCCN query is used only for the records that carry that number
themselves (MARC 020 `$a`, the ten- and thirteen-digit forms of one ISBN counting as the
same; MARC 010, normalised): an answer that echoes the query and holds another record is
refused. The proposal keeps the record it was built from (`choices`: its catalogue id,
LCCN, ISBNs, and the field that matched), and the catalogue check's verdict counts for the
proposal only when it accepts that same record.

Catalogue text is plain text. Before house braces are added it is escaped for TeX
(`book_build.plain_source`, using the escaper of `intake`): `%`, `&`, `#` and `_`. The
verifier compares the escaped field as equal to the record. A string with a backslash, a
dollar sign, `~` or `^` is not written (the verifier does not read their TeX forms), and a
name with any such character is not written either; the field is listed as unfilled.

A search that returns several records is answered with the records and builds none. No
DOI and no ISBN are written: the catalogue route is for a book without a supplied DOI, and
an ISBN is not a house field.

### A chapter record with two container titles

When a `book-chapter` record has two container titles, `cdlbib.container_titles` chooses
between them and can produce no other string: (1) a Crossref record of a book type with
one of the chapter's ISBNs whose title is one of the two; (2) the Library of Congress
record with one of those ISBNs whose transcribed title is one of the two; (3) only when
both answered and neither decides, and a model route is set up: the `extract` phase of the
research adapter reads the lines of the chapter's page at its publisher that mention
either title. The page is fetched from `doi.org` and the fixed publisher hosts of
`publisher_corrections` only, over HTTPS, each redirect checked before it is followed.
The fetch uses a session made for it that carries no credentials (`trust_env` off: no
`.netrc`, no proxy from the environment, so a machine that reaches the web only through a
proxy cannot fetch the page; no auth; an empty cookie jar that lives for the one fetch).
The host is resolved once to refuse private addresses and again by the connection; the
connection is not pinned to the first answer, and what bounds this is that the host is
one of the fixed public hosts and its certificate is verified, so another address cannot
complete the TLS handshake and receives no request. One deadline covers the whole
resolution, and it is enforced while bodies are read: the page, the catalogue's answer
and Crossref's book lookup are each read from the socket in bounded steps with the clock
checked before every step and a byte limit, and cancelled when either is passed.
The model's choice counts only when its book title is one of the two and its passages lie
on that page; what is judged is every whole line a passage touches, never the part of a
line the model selected: one of those lines must hold the chosen title without the other,
and none may hold the other alone. The result is recorded on the proposal (`choices`: the record or, for a
model, the route, model, URL, quoted line and document hash), a model-assisted choice
makes the proposal need a decision, and the entry is verified afterwards by the ordinary
route. The verifier accepts either container title of such a record, so an entry with a
model-assisted title can read `metadata_verified` without the choice having been
confirmed. The proposal therefore keeps saying, in its issues (shown by the command line,
the terminal interface and the web interface) and in `choices` (`model_assisted: true`,
`confirmed: false`), that the choice is model-assisted and unconfirmed, and it is never
accepted without the person's decision. Once the entry is written, the library holds
only the entry: the gate's stored result does not carry that mark.

A chapter's editors, when its own record names none, are taken from the book's record by
the same lookups (`container_titles.book_editors`). Every record of the book in an answer
is read, not the first; records that name different editors, an answer Crossref cut short
(it counts more records than it returned), or an editor list with a member that is not a
person decide nothing. The source records are kept, and each comparison reads them again:
the record must be of a book type (never a series), carry one of the chapter's ISBNs, and
have as its title the container title that the entry's book title is.

### Local PDF discovery

To index a user-provided paper folder without changing it:

```sh
python -m cdlbib.local_library "/path/to/Papers" --bibliography cdl.bib
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
python -m cdlbib.local_ocr --bibliography cdl.bib
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
`src/cdlbib/arxiv_review.py`. It compares complete ordered author lists, titles,
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
`src/cdlbib/pdf_evidence.py` is a position-aware local-PDF verifier with a
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
|PsyArXiv|`src/cdlbib/osf_review.py`|OSF API v2: version list, bibliographic contributors, primary-file revisions|
|Software and data|`src/cdlbib/datacite_review.py`|DataCite REST API (`/dois/<doi>`, title search)|
|ACL Anthology|`src/cdlbib/acl_review.py`|`https://aclanthology.org/<id>.bib`; OpenAlex only nominates identifiers|
|SfN abstracts|`src/cdlbib/sfn_abstracts.py`|the abstractsonline.com meeting planner (2009-2015 meeting keys confirmed)|

A route can verify an entry, propose source-backed field values, flag a published
version for replacement, or hold the entry. Only PsyArXiv is supported among OSF
preprint servers (`osf_review.PROVIDERS`). A preprint is compared with its latest
version, and when OSF lists a published article DOI the entry is classed `replacement`
and never verifies. Software titles take the house form `{Owner}/repo: {version}` and
every creator is compared in order. The SfN route can confirm a meeting abstract, but
under the lab's rules conference abstracts are dropped from `cdl.bib` (see
[Decision rules](#decision-rules-for-what-the-library-contains)).

## Editors (resolvers 31 and 32)

Owner decision, 2026-10-06. The Crossref comparison (`verification.compare_record`)
compares an entry's `editor` field with the record's `editor` list exactly as it compares
authors (`author_evidence`, with the role named in the wording): the whole list, in order,
surnames equal, initials agreeing with the source's given names, suffixes ignored, a
byline listed twice counted once.

|Entry|Record|Result|
|-|-|-|
|no `editor` field|any|no editor evidence and no editor issue: the comparison is the one made before this rule|
|`editor` on `incollection`, `inproceedings` or `book`|names the same editors|`editor` evidence, no issue|
|the same|names other editors, another order or another number|`editor: Editor surnames/order differ`, `editor: Missing editors or different editor counts`, `editor: Editor given names differ`, and so on|
|the same|names no editors|`editor: the citation names editors and the source record names none`|
|`editor` on any other type|any|`editor: no deterministic verifier for this field`, as before|

This is an additive resolver change, so it raised `RESOLVER_VERSION` to 31 and not
`POLICY`. Before it, every entry with an `editor` field got the issue `editor: no
deterministic verifier for this field` from this comparison, so none was ever accepted
through it; the rule can therefore accept entries that were unresolved and cannot
withdraw an approval. Restoring `verification/baseline.jsonl.gz` and running `crossref
auto-review --offline` gives the same status for every entry before and after the change
(`human_verified=36, metadata_verified=6348`, and `pending` for the six entries added
since the baseline was saved), with every saved result byte for byte the same.

The entry builder (`complete.build`) writes a chapter's `Editor` from the chapter's own
record when the record names editors, in the house name form. It does not fill the
editors of a proceedings paper.

### A chapter's editors from the book's record (resolver 32)

Owner decision, 2026-10-06: a chapter's editors come from the book's record. Of the 227
chapters of the library with an `Editor` field, 122 have their accepted Crossref chapter
record saved, and none of those records names an editor.

`container_titles.book_editors` finds the book by the lookup that settles a chapter's book
title, and no other: for each of the chapter's ISBNs, Crossref's records of a book type
(`book`, `edited-book`, `monograph`, `reference-book`; never a series) and then the Library
of Congress record, each taken only when its title is one of the chapter record's container
titles. The requests, the cache and the bounds are those of that lookup.

|Found|Editors|
|-|-|
|one record of the book names editors|those editors|
|both name editors and agree (compared as a byline is compared with a source)|Crossref's|
|both name editors and disagree|none: "the book's Crossref record and its Library of Congress record name different editors, and neither is chosen"|
|a record of the book that names no editors (or one the catalogue check's grammar does not read)|none: "the book's own record names no editors"|
|no ISBN on the chapter's record, or no record with it under the book's title|none, with that reason|

The builder keeps what was found in the chapter's record under `book-record` and writes
`Editor` from it. The verifier does the same for a chapter cited with editors whose record
names none, when nothing else in the comparison is amiss (`verify_entry`): it looks the book
up, keeps what it found in the candidate's saved record, and `compare_record` compares the
entry's editors with it by the authors' rules. The saved evidence is judged again on every
comparison (`container_titles.valid_book_editors`): it counts only if it was found under one
of the chapter record's own ISBNs and a title that is one of its container titles, names
the source its editors came from, and records no disagreement. Offline reassessment
therefore needs no request. The issue for a mismatch ends "(the book's own record)".

Additive, so `RESOLVER_VERSION` 32 and the same `POLICY`: before it, such an entry had the
issue that its record names no editors. The offline recomputation over the baseline gives
every entry the status it had (the four book titles the owner had rewritten that day are
`pending`, as edited entries are). From saved records alone, 7 of the 227 chapters have a
saved record of their book that confirms their editors (Mann23, KahaEtal24, Mann24,
OReiEtal99, OhrtGron99, HealPark01, RoedEtal01a); for 3 the saved book record names the same
people without the middle initials the entry gives, which the name rules do not accept
(HashEtal08, BravEtal08, KaneEtal08); 92 have no saved chapter record, 7 a chapter record
without an ISBN, and for 118 no record of the book was ever saved. For eight chapters of the
library the book was looked up for the tests (KahaEtal24, Mann24, Klee56, BobrNorm75, Scha03,
AherBeat81, Mann23, MayeEtal92b): a record of the book named editors for all eight, six from
Crossref and two from the Library of Congress, and they are the library's editors for the
five of them whose library entry has any.

## Ordinals and acronyms in book titles (2026-10-06)

Owner decisions, 2026-10-06. Ordinals are numerals with a superscript suffix
(`30\textsuperscript{th}`), and acronyms in the titles of books and proceedings keep their
capitals in braces (`{IEEE}`). The format checker's formatter for `booktitle`
(`helpers.format_booktitle`) and for `edition` (`helpers.format_edition`) writes both, and
the builder uses the same formatter, so a built name is in the form the check accepts.

|Given|Written|
|-|-|
|`16th Annual International Conference`|`16\textsuperscript{th} Annual International Conference`|
|`the Fifth Annual Workshop`, `the Twenty-Third Annual Conference` (the ordinal numbers a meeting)|`the 5\textsuperscript{th} Annual Workshop`, `the 23\textsuperscript{rd} Annual Conference`|
|`Second Language Acquisition`, `the Twenty-First-Century University` (the ordinal is part of the wording)|unchanged|
|`the Thirty Years War`, `the 30 Annual Conference` (a cardinal)|unchanged|
|`the 3th Workshop` (a numeral with the wrong suffix)|unchanged|
|`NAACL-HLT`, `(MobiSys)`, `IEEE/CVF`, `ACM SIGKDD`|`{NAACL}-{HLT}`, `({MobiSys})`, `{IEEE/CVF}`, `{ACM} {SIGKDD}`|
|a name given wholly in capitals|formatted as before: no acronym is read in it|
|edition `Second`, `2nd`, `Second edition`, `2nd ed.`|`2\textsuperscript{nd}`|
|edition `2` (a cardinal), `3th` (a wrong suffix)|unchanged (the research route's own normaliser, `research_forms.normalise_edition`, writes both as ordinals)|

An ordinal word counts as numbering a meeting when the next word names a meeting
(conference, workshop, symposium, meeting, congress, colloquium, convention, seminar,
forum), with nothing between them but "annual", "biennial", "international", "national",
"joint" and the like, or braced acronyms. Other ordinal words are left as written.

The comparison reads the three spellings of an ordinal as equal (`verification.ordinal_form`,
which reads the superscript form too), in the Crossref comparison and, since this change, in
the ACL Anthology check's comparison of the proceedings' name.

LaTeX in a name is read as spans of the text as given and put back after the word rules
have run (`helpers._restore_spans`, for every field `format_journal_name` formats): the
name of a command, the braced arguments of a command of two letters or more, mathematics
between dollar signs, and a braced group that holds a capital and is not a caps-list word.
Accents are left to the word rules as before. The acronym rule braces the given text in
place; it puts no placeholder into the name. Comparing the formatter before and after this
on every Journal, Booktitle, Publisher, Address and Edition of `cdl.bib` and of the frozen
library fixture, and on every key of the three alias tables (16,922 values), no result
differs.

Entries already in the library that a new house rule would change can be held on a list,
`src/cdlbib/data/pending_house_forms.json`, each with its present and its proposed text. The
format check prints a listed entry on every run and does not count it as an error while it
is exactly as listed; `--autofix` does not change it. Every other entry, and a listed entry
whose text is anything else, is held to the rule. The list is empty. The ordinal rule
changed four book titles (ClanEtal19, BoseEtal92, SilbEtal01, Beaz96), which were held on
the list and then rewritten in `cdl.bib` on 2026-10-06 with the owner's approval. Their
text changed, so their saved results no longer apply until they are approved again.

## Builder rules left as built (2026-10-06)

Two things the entry builder does were confirmed as they are:

- A chapter's publisher is written from the Crossref record only when the format check's
  publisher formatter leaves the registry's name as it is. A name the formatter turns into
  another name (`Springer New York` becomes `Springer`) or respells (`Springer US` becomes
  `Springer Us`) is not written, and the proposal lists it as unfilled: the registry names
  the current depositor, which may not be the publisher printed in the book (AherBeat81:
  Crossref has `Springer US`, the book's imprint is Plenum Press).
- The name of proceedings is written without its year and without the acronym in
  parentheses at its end (`verification.proceedings_name_forms`), the form the comparison
  accepts for a source name with either.

The builder reads the ACL Anthology's own record of an Anthology paper (through the
Anthology check's client and cache, `acl_review.collect`) and takes the pages from it;
Crossref's pages are proposed as a question only when the Anthology cannot be read or
states no pages. The proposal is then checked as the gate checks it: when the Crossref
comparison does not accept the entry, the Anthology check judges it.

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

`src/cdlbib/research_route.py` covers the entries that the September 2026 research waves
verified field by field. Their saved results in `verification/baseline.jsonl.gz` have
status `metadata_verified` and `accepted_source = research-evidence`; each records, for
every field, the researched value, the quotation, the source URL and the sha256 of the
fetched page. The research files, the route's design notes and the
`crossref research-approve` command that built these results from them are in the
archive repository ([research-route-2026-09-27/README.md](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/research-route-2026-09-27/README.md)).
The command is not on this branch, because it read those research files; neither is
the code that read them or its tests (tests/fixtures/research_route/). What stays in
`src/cdlbib/research_route.py` is the re-check below and everything it calls.

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
research validator's quote matching (`src/cdlbib/research_quotes.py`) and the post-check's
house normalisers (`src/cdlbib/research_forms.py`), both copied unchanged from the research
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
dispatch. All jobs share one serial concurrency group. The shared
`.github/actions/crossref-contact` action supplies the public CI contact from its
`mailto.txt`; the repository's `CROSSREF_MAILTO` Actions variable overrides it when
available. This lets fork pull requests run when GitHub supplies an empty variable.

- On a pull request or push, it writes the base revision's `cdl.bib` to
  `.bibcheck/base.bib`, restores the base revision's `verification/baseline.jsonl.gz`
  (never the snapshot in the pull request), and runs
  `crossref verify cdl.bib --auto-review --against .bibcheck/base.bib`. Only new or
  edited content is gated; key-only renames are excluded. It also writes the base
  revision's `verification/approvals.jsonl` to `.bibcheck/base-approvals.jsonl` (an empty
  file when the base has none) and passes it as `--trusted-approvals`, so the checker
  reads approvals from that copy and not from the pull request's file. The base revision's
  `verification/revocations.jsonl` is written to `.bibcheck/base-revocations.jsonl` and
  passed as `--trusted-revocations` to `restore` and `verify`, which add its rows to the
  database's `revocations` table; they count together with the rows of the pull request's
  own file, so a pull request that deletes a revocation line does not undo it.
- A push whose base revision is not in the history (a force-push, rewritten history, or
  a new branch) has nothing to compare against. Its content is already merged, so the job
  restores the pushed commit's own `verification/baseline.jsonl.gz` and runs
  `crossref status cdl.bib` (offline): every entry must have an accepted result for its
  exact current text. Pull requests never take this path; one without a base is refused.
- A manual run restores the committed baseline and checks the whole library.
- The last two read the checked-out commit's own `verification/approvals.jsonl`.
- The SQLite database is kept in the Actions cache, keyed by ref; a pull request can
  fall back to the `master` cache, and `master` never restores a pull-request cache. The
  report and a checkpoint snapshot are uploaded as artifacts. The cache only saves
  lookups: an approval in it can come only from the checker's own runs, never from a
  file in the pull request.
- Exit status: `0` when every selected entry is verified, `1` otherwise, `2` for a
  configuration or provider error.

Because approvals are trusted only from the base branch, a pull request that adds a
`human_verified` approval to `baseline.jsonl.gz`, or a row to `approvals.jsonl`, still
fails its own check for an entry it also adds or edits; a maintainer merges it after
checking the approval. A pull request that only adds rows to `approvals.jsonl` changes no
entry, so no entry is selected and the check passes without reading those rows. The job runs the pull
request's own code, so this guarantee assumes the checker itself is unchanged; review any
change under `src/cdlbib/` or `verification/check_ci.py` separately.

The separate `autocheck` workflow runs `cdlbib verify --no-citations` (the formatting
check of `cdl.bib`) and `pytest tests` on Python 3.11 and 3.13 (job `test`), and builds the
wheel and installs it into an empty environment (job `build`). Before the system's TeX is
installed, the `test` job runs `tests/test_texinstall.py` with `CDLBIB_TEST_TEX_INSTALL=1`:
the tests that install biber and BibTeX for real, into a TeX Live of their own (TinyTeX,
about 140 MB with biber). They assert that `biber` and `bibtex` are absent until
installed, and their `PATH` includes `/usr/bin`, so they cannot run after the `apt`
packages put both there; the step fails first if the runner already has one.
