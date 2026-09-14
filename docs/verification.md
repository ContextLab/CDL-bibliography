# Citation verification design

## Accuracy contract

The program establishes agreement with recorded source metadata. It cannot guarantee that a database deposit is correct, that a finite search found every competing work, that an initial uniquely identifies a person, or that the final rendered bibliography follows every submission requirement. Neither an LLM assertion nor the absence of a detected mismatch is sufficient evidence.

The default gate accepts `metadata_verified` and `human_verified`; `status --require-human` accepts only the latter. The comparison is deliberately conservative. Abbreviated journals, incomplete deposits, translated titles, mathematical titles, editions and competing publication dates often require review. The automatic review layers described below resolve supported cases before human review.

A wrong DOI is particularly important: the DOI must agree with the title, authors, version and remaining fields. Finding an apparently correct paper elsewhere never silently repairs the supplied identifier. Automatic code never changes the bibliography. `force` is a formatting setting, not an accuracy exception.

## Stages and persistence

1. Strictly scan and parse the entire bibliography before any network calls. Reject duplicate keys/fields, parser omissions, malformed entries and invalid inheritance.
2. Fingerprint the exact raw entry plus string/preamble definitions and inherited entry fingerprints. Look up a review indexed by bibliography path, citation key, fingerprint and comparison-policy version.
3. For an uncached entry, fetch its DOI record or search Crossref for candidates. Query construction uses the title, first author, year and venue; all authors are checked during comparison. No fuzzy score grants approval.
4. Compare publication type, title/subtitle, complete ordered authors, year, venue and supported fields. Missing evidence and conflicting dates block approval. Keep all candidate records and comparisons for review.
5. Where relevant, collect DataCite DOI or arXiv identifier evidence. Their date/type semantics are not silently converted into journal metadata. This implementation does not automatically approve these fallback records.
6. Optionally invoke a configured web-search/PDF adapter for an unresolved entry. Download the actual PDF, extract its text and validate quotations against page text. Retain the result for human review.
7. Record explicit human decisions only with reviewer, source, notes and the exact fingerprint. A stale fingerprint is rejected.
8. Checkpoint each result in a SQLite transaction. Regenerate the final report from a fresh bibliography read, so edits during a run remain pending.

The initial pass visits every entry; it does not imply every entry is verified. Subsequent ordinary runs visit only new/modified entries and entries with provider failures. Existing review findings are retained until explicitly retried. An outage stops the run; rerunning resumes from checkpoints.

### Invalidation details

The verification state is derived from the current source fingerprint. Old rows are immutable audit history, not unconditional approvals. A whitespace-only edit, field reorder, key change, added unknown field or manual approval followed by an edit loses current approval without any network or model call. Changing a parent entry invalidates its descendants; changing a shared string or preamble conservatively invalidates all entries.

Deletion removes an entry from the current report. A rename is a different raw entry. Restoring the exact previously reviewed content can reuse its historical matching review. There is no watcher that detects transient edits made and reverted between invocations. Every consumer must use `current_results`/`status`, not query historical SQLite rows as if they were current status. Static reports and exported snapshots must likewise be checked against the live bibliography before use.

Change `POLICY` when altering acceptance criteria or normalization semantics. A version mismatch invalidates cached reviews, including human decisions, conservatively. Query-only changes do not need to invalidate already supported reviews. HTTP responses can be reused while applying a new comparison policy.

### Storage choice

SQLite is the working store: indexed lookup, append-only review history, transactional writes and resumability scale beyond this bibliography. The database contains `reviews` and a separate `responses` table. The latter stores request identity, retrieval time, HTTP status, source URL and relevant metadata; abstracts and reference lists are excluded. No external database service is required.

A single JSON object would require repeated whole-file rewrites and careful locking; a bare text list of keys would miss edits and lack evidence. JSON Lines is useful for sequential inspection/export but lacks efficient keyed updates. Compressed JSONL snapshots provide a portable audit artifact; SQLite provides local operation. The changing database, PDF downloads and report are ignored by Git. Snapshots can be shared or committed intentionally.

Snapshots have a schema/policy header and one record per entry. Restore validates the complete file before writes, maps reviews to the destination bibliography path, accepts matching fingerprints only, and does not overwrite local reviews. Snapshot files are trusted data, not cryptographic certificates. They exclude HTTP cache entries and downloaded PDF bytes; archive those separately if needed.

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

## Operational limits

- Crossref deposits can be incomplete or incorrect. A metadata match is not independent corroboration from the PDF.
- Automatic journal checks support `article`, `inproceedings`, `book`, and `incollection` only when the Crossref type agrees. Other types and additional fields require review.
- A finite candidate set cannot establish global uniqueness. Exact title/author competitors among retrieved records block approval.
- Initials agree with given names but do not establish personal identity. Use human source review for the stronger gate.
- Direct Crossref publication dates must collapse to a single year. A separately identified PubMed issue record can resolve an online/print split only when it confirms the print year plus the same volume and pages. No automatic ±1-year tolerance is used.
- Review status does not expire on a timer. Use `--refresh` for an intentional fresh-source audit, including newly deposited corrections and relationships.
- Run `status` on the actual manuscript keys and inspect the rendered bibliography before submission. Neither the formatter nor cached metadata certifies the rendered artifact.

## Automatic review (comparison policy 2)

`auto-review --offline` recomputes candidate comparisons from saved evidence, including fingerprint-matching rows from an older policy. It does not carry an old human approval forward. Changed entries have no eligible old review and remain pending until initial verification. The policy-1 snapshot is historical; current clones should restore the policy-2 baseline. The old rows remain in SQLite audit history.

Policy 2 distinguishes omitted optional issue numbers from incorrect supplied numbers. Omission is advisory only if the volume and full pagination already agree. It also preserves literal ampersands/percent signs/hash signs before LaTeX conversion; the old converter could erase them. Ampersand/“and” equivalence is restricted to journal names. Crossref `has-review`, `references`, and `is-referenced-by` relations are evidence annotations, not version conflicts. Unknown and version/update relations still block direct verification. These decisions are based on [BibTeX's entry definitions](https://www.openoffice.org/bibliographic/btxdoc.html) and [Crossref's relationship semantics](https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/).

`auto-review` batches up to 25 exact, quoted DOI queries into a single Europe PMC request. It uses only identified PubMed (`MED`) records; DOI mismatches, malformed/truncated results, and duplicate PubMed identities cannot authorize an entry. The same paced client, bounded retries, cache, and process lock are reused. Search results are discovery only. Missing identifiers are not guessed. Completed negative searches are checkpointed, and provider errors stop the run without marking unqueried targets as absent.

The second-source comparator resolves only specified cases: a journal-issue year that matches the Crossref print year and the same volume/pages; more complete compatible given names; source-supplied journal names linked by a shared ISSN; and full pagination that completes a matching first-page-only deposit. Full conflicting given names, wrong pages, titles, types, and supplied DOI differences cannot be outvoted. MEDLINE terminal title punctuation and abbreviated ending pages are handled explicitly, preserving accents, subtitles, and page prefixes. [Europe PMC API reference](https://europepmc.org/RestfulWebService).

`fulltext-review` uses open-access PMC identifiers obtained during that pass. It reads top-level `front/article-meta` and `front/journal-meta` from the actual XML, never metadata from a cited reference in the body/back matter. The DOI must match both Crossref and PubMed. Full source title, ordered authors, and every supplied supported field must agree. PubMed's journal-issue year must occur in an explicit source publication date; its volume and pagination must agree too. Copyright, acceptance, receipt, and download years cannot supply the publication date. Author manuscripts, preprints, revised archive versions, corrections, unknown semantic markup, and unresolved type/version relationships remain blocked. The initial `pmc-version=1` archive annotation is not a preprint designation. [JATS publication dates](https://jats.nlm.nih.gov/archiving/tag-library/1.2/element/pub-date.html).

The primary article source may adjudicate incomplete/different registry fields when all checks pass; it cannot silently substitute another DOI or a preprint/final version. Results distinguish `accepted_source=crossref`, `europepmc`, and `pmc-jats`, but all are machine metadata checks, not human review or an absolute accuracy guarantee. Full XML stays in the local HTTP cache. Portable evidence retains metadata front matter and the original document SHA-256, excluding the article body and abstract.

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

`bibcheck/dartmouth_research_adapter.py` uses Dartmouth's documented `/api/chat/completions` endpoint and `DARTMOUTH_CHAT_API_KEY`. `BIBCHECK_RESEARCH_MODEL` defaults to the live-confirmed `qwen.qwen3.5-122b` ID. `--check-model` checks `/api/models` and fails if that exact ID is absent; it never substitutes another provider. See [Dartmouth API usage](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/basic_usage/) and [model discovery](https://rcweb.dartmouth.edu/~d20964h/2024-12-11-dartmouth-chat-api/model_list/).

The model uses a client-side JSON action loop, so native function calling or hosted search support is not required. It can request `web_search(query)`, see the results, revise its query, select a retrieved PDF source by index, or report that the source remains unresolved. Only these actions are interpreted; no shell commands, arbitrary functions, or model-supplied URLs execute. Tool data is explicitly untrusted. Allowed hosts govern page and PDF retrieval, including redirects. URLs from registry records and publisher `citation_pdf_url` metadata can also supply candidates. A link is a discovery clue, not evidence that the publication/version matches.

`bibcheck/search_tools.py` provides two explicitly selected free backends:

- `BIBCHECK_SEARCH_BACKEND=europepmc` (default): the [Europe PMC REST API](https://europepmc.org/RestfulWebService), including full-text PDF links when supplied by its records. It covers scholarly literature, not general web content.
- `BIBCHECK_SEARCH_BACKEND=duckduckgo`: a parser for DuckDuckGo's public HTML search interface. This is experimental, not an official search-results API or the Instant Answer API. Challenges, throttling, and unrecognized pages fail without proxy rotation, challenge bypass, or automatic retry. There is no silent provider fallback.

Each search returns up to five results. Successful queries, including recognized empty results, are cached for seven days in `.bibcheck/search.sqlite3`; change its location with `BIBCHECK_SEARCH_CACHE`. Uncached queries wait three seconds, source requests wait one second, and Dartmouth calls wait two seconds. Runs are serial within the existing research batch lock; the Actions workflow additionally serializes its jobs. Do not launch independent research processes with different verification databases to evade pacing. Cached discovery results never change a verification status or defeat exact-entry invalidation.

Per entry, discovery permits at most three distinct searches, four model responses, three landing-page lookups (each with at most four requests including redirects), and twenty candidate PDFs. Extraction adds one model response. Each model request caps input data at 100 KB and output at 4,000 tokens. The adapter timeout is 600 seconds per phase to accommodate this bounded loop. Each discovery model response has a 90-second read timeout; PDF extraction allows 240 seconds after a live extraction exceeded the original 90-second limit. Refused, truncated, malformed, or unsupported responses fail closed. These limits bound requests, not model accuracy. JSON is requested in the prompt and checked locally; strict provider JSON-schema support is not assumed. Optional Markdown fences are removed without changing JSON values. Duplicate JSON keys, trailing prose, multiple objects, and invalid field evidence are rejected. For `qwen.qwen3.5-122b`, requests use Qwen’s documented direct-response settings (`chat_template_kwargs.enable_thinking=false`, temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5). These settings are based on the [official Qwen model guide](https://huggingface.co/Qwen/Qwen3.5-122B-A10B); gateway support must be validated live and the settings are not an accuracy guarantee.

Publisher landing-page discovery reads `citation_*` metadata only from HTML head tags, excluding body/reference-list tags and retaining conflicting values. Its supplied PDF links become candidates; this is discovery evidence, not a new HTML acceptance rule. Qwen may select a retrieved publisher PDF without making a general search call. PDF selection returns only an existing source index. Up to two alternative PDF links from that same retrieved record may accompany it; links from other candidate publications cannot be substituted. Bibcheck tries at most three supplied copies after download failures and records each attempt. This does not establish that mirrors have identical publication versions. Bibcheck downloads the actual PDF and saves its hash and first five pages of extracted text. Dartmouth extraction receives numbered source passages without the input BibTeX fields. Qwen returns field values and passage IDs; Python copies the exact original slices and validates every page, offset, and quotation. Unknown IDs and duplicate non-author fields fail closed. Individual author selections are assembled in source order. Conservative literal checks preserve accents and subtitles and flag inferred values; BibTeX entry type always requires interpretation. Literal support does not establish field role, identity, author completeness, or publication version. Because a receipt date, a copyright notice, a preprint version stamp, an affiliation line and a reference-list entry are all literally present on the page, each field's evidence additionally carries a `role_risk` list, collected in `role_risk_fields`, naming printed roles that make the proposed value suspect: `reference_list`, `receipt_or_revision_date`, `copyright_line`, `preprint_version_stamp`, `affiliation_line`, `institution_named_as_venue` and `possible_omitted_author`. Each match also becomes an explicit uncertainty. These are pattern heuristics over the selected passages, never an approval and never a rejection; they deliberately over-flag, because a false positive withholds acceptance while a false negative would admit a wrong value. An empty `role_risk` is not evidence that the role is correct. The generic adapter contract above remains supported for other providers. Both discovery and extraction uncertainties survive in the evidence. Successful evidence includes the search queries/results, source URLs, timestamps, cache-use indicators, and model usage. Failed research attempts are checkpointed; successful search results remain cached even if later model/PDF processing fails. Neither adapter edits BibTeX or grants verification.

The manual `.github/workflows/dartmouth-research.yml` pilot consumes the GitHub repository secret, checks model availability, and defaults to three entries (maximum ten). Inputs reach commands through environment variables and argument lists, not interpolated shell code. It restores the portable baseline and caches `.bibcheck` between runs; edited entries still lose eligibility automatically. An always-run checkpoint exports a snapshot artifact, including failure records. PDFs stay in the runner/cache, not the artifact. A GitHub cache is temporary storage and can be evicted. No credentials appear in snapshots or model prompts. Existing attempts are skipped unless the explicit retry input is enabled.

Validation: both search connectors returned real results in a September 9, 2026 probe; DuckDuckGo found the proceedings PDF and arXiv record for “Attention Is All You Need.” Local tests cover adaptive query revision, persistent caching, fabricated source indexes, invalid quotations, budgets, blocked redirects, and challenge handling. Live Dartmouth authentication and Qwen search actions have now succeeded. Testing exposed DuckDuckGo HTTP 202 challenges, a stale publisher PDF returning 404, and Europe PMC PDF throttling (429). These failures remain unresolved rather than becoming approvals. The exact live model ID is `qwen.qwen3.5-122b`. GitHub cannot reveal an Actions secret for local use, and the new manual workflow must be published to the default branch before dispatch.


### Local credentials and live debugging

If `DARTMOUTH_CHAT_API_KEY` is unset, the Dartmouth adapter reads `.bibcheck/secrets/dartmouth_chat_api_key.txt` (or `BIBCHECK_DARTMOUTH_KEY_FILE`). The local secrets directory is ignored by Git; use directory permissions `700` and file permissions `600`. The environment variable takes precedence. The key must be a single nonempty token. Never include it in source files, command arguments, reports, or prompts.

`python verification/dartmouth_pilot.py --key ElSo18 --backend europepmc` runs a bounded live attempt without altering the bibliography or verification database. Diagnostics and returned model evidence are saved under ignored `.bibcheck/debug/` with restricted permissions; credentials are redacted before diagnostic writes. Diagnostic responses retain content, usage and sanitized errors, excluding request headers and model reasoning text. `--allow-host` adds an exact permitted source host. `--landing-url` starts discovery from a known publisher page, fetching its metadata before model selection. `--source-url` skips discovery to isolate extraction against an already retrieved PDF; its evidence explicitly records that discovery was not exercised in that run. The script checks the model ID, downloads the actual PDF, extracts up to the first five pages (`--pages 1` isolates the front page), and applies the same quote checks as production research. A successful extraction probe is not evidence of a successful end-to-end search run or a citation approval.


The [earlier live pilot](../verification/dartmouth-live-pilot.md) exposed an invented ellipsis and an inferred series title. The [follow-up benchmark](../verification/benchmark/README.md) records source-passage extraction and a complete known publisher-page → PDF → Qwen evidence run, with all quotations passing. Its 60 offline cases across 30 real entries test documentary metadata comparisons, not 30 independent PDF reviews or model accuracy. The ten-entry expanded Crossref pilot accepted no additional entries. Broad-batch reliability and automatic PDF adjudication remain unestablished; all model findings stay `needs_review`.
