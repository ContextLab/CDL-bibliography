# Contextual Dynamics Laboratory bibliography

![autocheck](https://github.com/ContextLab/CDL-bibliography/workflows/autocheck/badge.svg) [![DOI](https://zenodo.org/badge/69401856.svg)](https://zenodo.org/badge/latestdoi/69401856)

[cdl.bib](cdl.bib) is the shared BibTeX bibliography of the [Contextual Dynamics Lab](https://www.context-lab.com/) at Dartmouth College. This repository also provides tools for checking citation formatting and comparing bibliographic metadata with external sources.

**A formatting pass is not an accuracy check. A metadata match is not a guarantee that a citation is correct.** External databases can contain errors or omit information. Before submission, resolve outstanding findings for the references actually used in your manuscript and inspect the rendered bibliography against the cited sources.

## Contents

- [Installation](#installation)
- [Suggested workflow](#suggested-workflow)
- [Citation accuracy and Crossref](#citation-accuracy-and-crossref)
- [Formatting, comparison, and commits](#formatting-comparison-and-commits)
- [Using the bibliography in LaTeX](#using-the-bibliography-in-latex)
- [Using the bibliography on Overleaf](#using-the-bibliography-on-overleaf)
- [Development](#development)

## Installation

Run commands from the repository root. Python 3.11 is the tested environment for the complete toolset; use a virtual environment to isolate its dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python bibcheck.py --help
```

For only citation accuracy checking, install `requirements-verification.txt` instead. That path does not need NumPy, pandas, or the formatting lookup tables and supports Python 3.9+. The optional PDF research command additionally needs `requirements-research.txt` and a configured research adapter.

The formatter and verification runner are intended for macOS and Linux. The verification runner uses an OS file lock to prevent concurrent runs against the same cache.

## Suggested workflow

1. Add or edit entries in `cdl.bib`, preserving the DOI and the exact publication version you intend to cite.
2. Check the format and verify the citations of the new or edited entries:

   ```bash
   export CROSSREF_MAILTO='your-real-contact-address@institution.edu'
   python bibcheck.py verify --verbose
   ```

   `verify` runs one gate, shared with `commit`: (1) the format check; (2) `crossref verify --auto-review` on the entries that are new or edited relative to the GitHub `master` bibliography (the file `compare` uses; key-only renames are excluded); (3) an offline library-wide status line (verified / unresolved). It exits **1** when the format check fails or any new/edited entry is unresolved, and prints each such key with its issues. The library-wide backlog is reported but does not fail `verify`. Options: `--no-citations` for an offline, format-only check; `--all` to verify the citations of every entry; `--reference other.bib` to compare against another base; `--database` for another verification cache.

3. To run only the citation verification, with more control:

   ```bash
   python bibcheck.py crossref verify cdl.bib --auto-review
   ```

4. Resolve findings in `.bibcheck/report.jsonl`. Correct the BibTeX from the actual source, then rerun verification. For sources needing human review, use the workflow below.
5. Before submission, check the current verification status. To check only a manuscript's references, create `manuscript-keys.txt` with one citation key per line:

   ```bash
   python bibcheck.py crossref status cdl.bib --keys manuscript-keys.txt
   # Stronger gate: require an explicit human source review for every selected citation.
   python bibcheck.py crossref status cdl.bib --keys manuscript-keys.txt --require-human
   ```

6. Inspect the diff, then commit the bibliography with `python bibcheck.py commit`, or commit the bibliography/code changes you intend to share with Git directly, and push or open a pull request. A portable review snapshot can accompany the changes; see below.

`python bibcheck.py commit` runs the same gate as `verify` and **refuses to commit** (exit 1) while the format check fails or any new/edited entry is unresolved; it lists each unresolved key with its issues and points to `crossref review-packet` and `crossref approve`. When the gate passes, it commits only the bibliography file, with a message summarizing the added, removed and modified entries. It does not push. CI runs formatting and offline regression tests; it does not certify external metadata or approve unresolved references.

## Citation accuracy and Crossref

The integrated command is `python bibcheck.py crossref`. `python bibverify.py` is a compatibility entry point to the same implementation. The previous fuzzy, parallel verifier has been replaced; its `--workers`, `--parallel`, and `--autofix` options are no longer supported.

```bash
# Initial pass: check uncached entries and export a portable audit snapshot.
python bibcheck.py crossref verify cdl.bib --snapshot verification/baseline.jsonl.gz

# Subsequent runs: checks new/modified entries and retries provider failures.
python bibcheck.py crossref verify cdl.bib

# Revisit unchanged entries awaiting review, reusing cached HTTP responses.
python bibcheck.py crossref verify cdl.bib --retry-unresolved

# Recheck everything, including fresh requests to external sources.
python bibcheck.py crossref verify cdl.bib --refresh

# Audit cached machine approvals against their saved source evidence.
python bibcheck.py crossref verify cdl.bib --recheck-cached

# Limit work for a trial run; unchecked entries remain pending.
python bibcheck.py crossref verify cdl.bib --limit 10

# Offline: reread the bibliography, invalidate stale reviews, and write a report.
python bibcheck.py crossref status cdl.bib
```

`verify` and `status` exit **0** only when every selected entry has an accepted status, **1** when unresolved entries remain, and **2** on a parsing, configuration, or provider error. A completed initial pass can therefore exit 1: “checked” does not mean “verified.” Reports include entry fingerprints, source metadata, field comparisons, candidate DOIs, request URLs, and retrieval dates.

### What is checked

The checker first looks up an explicit DOI. Without a DOI, it retrieves up to five Crossref search candidates and compares their metadata. Search rank and fuzzy similarity never authorize an entry. A supplied DOI that disagrees with the citation is a review finding, even if another paper has a similar title.

Automatic verification requires supported publication type, complete title/subtitle, full author list in order, publication year, and the applicable venue. Every supplied supported field must agree with the source, including volume, issue, pages/article number, publisher, DOI, ISBN, and ISSN. Missing local volume/page information is flagged when the source supplies it. An omitted issue number is advisory when the volume and full pagination already agree; a supplied but incorrect issue number still blocks verification. Unsupported fields or types require review; `force` never bypasses accuracy checks.

Typography normalization retains brace-protected words, accents, punctuation, and text after a colon. It handles supported LaTeX accents, Unicode, capitalization, typographic quotes, and page-range dashes. Unknown LaTeX commands, math, and semantic markup require source review. Author initials may match source given names, but author counts/order, surnames, suffixes, and supplied middle names/initials must agree. Conflicting full names are not reduced to matching initials.

Preprints are not silently replaced with final publications. Online/print year differences can be resolved automatically when a PubMed journal-issue record confirms the cited year, volume, and pages. Unresolved date conflicts, related versions, and source update/correction relationships remain flagged. Links to reviews or references are retained as evidence but do not by themselves indicate another publication version. Journal abbreviations, shortened page ranges, edited volumes, editions, and incomplete deposited metadata can also require review even when the citation is valid.

### Verification statuses

| Status | Meaning | Passes the default gate? |
| --- | --- | --- |
| `metadata_verified` | Supported metadata agrees under the documented comparison policy. This is source consistency, not proof of correctness. | Yes |
| `human_verified` | A named human recorded source/edition review for this exact entry. | Yes |
| `needs_review` | Missing evidence, a discrepancy, ambiguity, or unsupported metadata. | No |
| `provider_error` | A service/network failure prevented checking. | No |
| `pending` | No review matches the current entry and policy. | No |

`--require-human` accepts only `human_verified`. Neither mode guarantees zero human or source errors. Finite search results cannot prove that no competing work exists.

### Server-friendly requests

A real contact email is required, through `CROSSREF_MAILTO` or `--mailto`, to identify the client to Crossref. Requests use a persistent connection and run one at a time. The default interval is one second after each response, adjustable with `--interval` to a minimum of 0.5 seconds. The client honors advertised rate limits, slows down after 429/5xx responses, respects `Retry-After`, and uses bounded retries. An extended provider failure stops the run with a checkpoint instead of querying every remaining entry during an outage.

Successful responses, including genuine 404 responses, are cached for 30 days. Timeouts, malformed responses, and other service failures are not recorded as “not found.” Reviewed entries remain cached until edited, the verification policy changes, or `--refresh` is requested; the HTTP cache's expiration alone does not invalidate a review.

The Python client also supports small batches of up to 20 explicit DOIs through Crossref's DOI filters. Normal verification uses singleton DOI lookups: Crossref identifies those as lighter operations. Independent bibliographic searches cannot be combined into one equivalent batch query. With thousands of entries lacking DOIs, the first pass can take hours; later runs reuse existing reviews.

See [Crossref's request guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/) and [July 2026 rate-limit changes](https://community.crossref.org/t/refining-rest-api-limits-for-improved-stability-and-reliability/16137). Avoid simultaneous jobs or multiple caches that collectively exceed the limits for your contact address/IP.

### Cache, invalidation, and the initial baseline

The initial Crossref pass checked all 6,422 entries. The subsequent [automatic review](verification/automatic-review.md) increased accepted metadata matches from 805 to 1,852, leaving 4,570 unresolved. The [current baseline](verification/README.md) includes those unresolved findings; it does not certify the whole bibliography. All figures describe the September 9, 2026 source snapshot.

The working database is `.bibcheck/verification.sqlite3`, beside the bibliography. SQLite provides indexed lookup, transactional checkpoints, and an audit history without rewriting the whole database after each reference. `--database` and `--report` override output locations.

A SHA-256 fingerprint covers the **exact entry text except its citation-key token**, including whitespace, field order, entry type, and braces. A key-only rename reuses the existing decision and check time. Every other entry edit triggers a new check, even when it only changes formatting or an unsupported field. Shared `@string`/preamble definitions and inherited `crossref`/`xdata` entries are included in the dependency fingerprint. Changing these invalidates affected approvals automatically. Duplicate keys, duplicate fields, malformed input, and missing/cyclic inheritance fail closed.

The key-independent fingerprint format is `v2`; the metadata comparison policy remains 2. Existing database reviews migrate automatically when their old fingerprints match exactly. Run `status` once before renaming keys in an unmigrated local cache. New snapshots support renames across clones; old snapshots can migrate only entries whose original keys and content still match. Historical evidence and verification times are preserved.

### Automatic checks on new and edited entries

The `Citation verification` workflow checks every pull request and push to `master`. It compares content against the base bibliography, checks new or edited entries through the free source layers, and fails for unresolved findings or provider errors. An unchanged legacy backlog is reported but does not fail the incremental gate. A key-only rename is excluded from the change set. Deleting an entry removes it from the current report.

Before activating the workflow, set the repository Actions variable `CROSSREF_MAILTO` to a real maintainer contact. The workflow must be published to GitHub to run; add `Citation verification / citations` as a required branch-protection check if merges must be prevented on failure. Fully cached runs need no contact or network access. The existing `autocheck` workflow still validates formatting and tests.

The local equivalent uses a base bibliography file:

```bash
git show master:cdl.bib > /tmp/cdl-base.bib
python bibcheck.py crossref verify cdl.bib --against /tmp/cdl-base.bib --auto-review
```

Use `--keys manuscript-keys.txt` instead of `--against` to select explicit keys. Reports and snapshots always include the full bibliography; the command's exit status gates the selected entries. All free review layers respect the selection. A manual Actions run checks the entire library and resumes any incomplete backfill. The existing baseline already contains one completed check for every entry; 4,570 unresolved entries still need better evidence or corrections.

CI persists SQLite between runs and always uploads a portable checkpoint and full report when available, including on failure. PR caches are scoped to their PR ref; the default branch restores only its own cache. PR baseline evidence comes from the base revision. GitHub caches/artifacts can expire, so periodically download the checkpoint and intentionally update `verification/baseline.jsonl.gz` to preserve new decisions durably. Cache eviction can require repeating checks absent from the committed snapshot. Snapshots remain trusted audit data, not independently signed approvals.

Invalidation is deterministic and local: every `verify`, `status`, and review operation rereads the BibTeX and checks its fingerprint. No human, LLM, or network request is needed. Historical database rows remain as audit evidence; they are never returned as current approval for different content. There is no background file watcher, and an exported report is a point-in-time artifact: run `status` against the actual bibliography before relying on a result. Returning to the exact previously reviewed content can reuse its matching review.

Run the initial `verify` once, resuming the same command after interruption. It saves each completed entry independently. Unchanged `needs_review` entries are retained in the review queue rather than repeatedly querying Crossref. Use `--retry-unresolved` deliberately to revisit them. Edits during a run are detected when the final report is regenerated.

`--snapshot PATH` exports a snapshot when a run stops, including a checkpoint after interruption or provider failure. Check its statuses before treating it as a completed baseline: pending/error entries remain unresolved. `--wait` queues a run behind another process using the same cache. Offline `status` and `snapshot` can read checkpoints while verification runs.

The SQLite database and downloaded PDFs are local, ignored files. For backup or sharing across clones, export a compressed JSON Lines snapshot:

```bash
python bibcheck.py crossref snapshot verification/baseline.jsonl.gz
python bibcheck.py crossref restore verification/baseline.jsonl.gz
```

Snapshots contain evidence and statuses, including unresolved entries, and can be committed or otherwise shared. Restore accepts only matching fingerprints and policy versions and preserves existing local reviews. Treat snapshots like trusted repository data, not signed certificates. They do not contain the HTTP response cache or downloaded PDF files. JSONL can be inspected by decompressing it; a changing monolithic JSON file or binary SQLite database is less suitable for sharing in Git.

### Automated review of flagged entries

The review queue is not a list of entries that must all be inspected manually. `python bibcheck.py crossref verify cdl.bib --auto-review` runs Crossref and both free review layers in sequence, reusing unchanged results. You can also run the layers separately:

```bash
# Reassess existing evidence without any network calls, including older-policy records.
python bibcheck.py crossref auto-review cdl.bib --offline

# Batch exact DOI lookups against PubMed records via Europe PMC.
python bibcheck.py crossref auto-review cdl.bib

# Read the article's own publisher front matter from open-access PMC XML.
python bibcheck.py crossref fulltext-review cdl.bib

# Try a broader Crossref title search for ten unresolved entries.
python bibcheck.py crossref discover-review cdl.bib --limit 10

# Export the current results after these layers.
python bibcheck.py crossref snapshot verification/baseline.jsonl.gz
```

These network commands checkpoint and skip entries already processed by that layer. `--limit 10` bounds a pilot. They do not edit citations or impersonate human reviews. DOI ambiguity, substantive source conflicts, unsupported fields, and version uncertainty stay unresolved. Publisher XML can correct incomplete registry evidence when its top-level DOI, title, full authors, and every cited field support the entry; the indexed issue year, volume, and pagination must also agree.

`discover-review` makes one focused title query with up to 20 Crossref candidates per eligible entry, using the same pacing, cache, and strict metadata comparisons. It defaults to ten entries, caps a run at 100, and accepts an optional `--keys` file with one citation key per line. It skips entries with attached external research evidence. It is a separate optional stage, not part of `verify --auto-review`. The [ten-entry live pilot](verification/benchmark/README.md) cleared no additional entries; repeating it made no network requests.

Optional LLM/PDF evidence collection is also batched and resumable:

```bash
# Set OPENAI_API_KEY securely in your environment, then choose an API model
# supporting Responses web search and structured output.
export BIBCHECK_RESEARCH_MODEL='your-configured-model'
python bibcheck.py crossref research-batch cdl.bib \
  --adapter bibcheck/openai_research_adapter.py \
  --allow-host arxiv.org --allow-host pmc.ncbi.nlm.nih.gov \
  --limit 10
```

Choose allowed hosts appropriate to the cited sources; add publisher/university hosts as needed, including PDF redirects. This optional command incurs provider charges. It defaults to ten entries, allows at most 100 per invocation, and skips previous attempts unless `--retry-failed` is supplied. Use `--keys manuscript-keys.txt` to prioritize references from an active manuscript. Three consecutive failures stop the run. The included adapter limits discovery to four web-tool calls and each model response to 4,000 output tokens; these are request limits, not a dollar spending cap. Set a provider spending limit before a large run. PDF quotations are checked against downloaded page text, and the findings remain available for adjudication. Neither a model's confidence nor matching quotations alone grant approval.

The included Dartmouth adapter uses Dartmouth Chat and defaults to full `zai-org.glm-5.3`, selected from the refreshed September 14 catalog. Dartmouth's **Local** tag denotes a free model even without a **Free** tag. Every adapter invocation checks the live catalog before inference; missing models, unknown eligibility, and explicit nonzero prices fail closed. It has a custom `web_search` tool: the model requests a query, receives actual results, and can revise the query before selecting a retrieved PDF.

```bash
# Use DARTMOUTH_CHAT_API_KEY, or the ignored local key file described below.
export BIBCHECK_RESEARCH_MODEL='zai-org.glm-5.3'
python bibcheck/dartmouth_models.py .bibcheck/dartmouth-models.json
export BIBCHECK_SEARCH_BACKEND='duckduckgo'  # or europepmc (the default)
python bibcheck/dartmouth_research_adapter.py --check-model
python bibcheck.py crossref research-batch cdl.bib \
  --adapter bibcheck/dartmouth_research_adapter.py \
  --allow-host arxiv.org --allow-host papers.nips.cc \
  --allow-host papers.neurips.cc --allow-host proceedings.neurips.cc \
  --limit 3
```

For local debugging, the adapter also reads `.bibcheck/secrets/dartmouth_chat_api_key.txt` when `DARTMOUTH_CHAT_API_KEY` is unset. Keep the containing directory mode `700` and the key file mode `600`; the directory is ignored by Git. `BIBCHECK_DARTMOUTH_KEY_FILE` selects another key-file path. The environment variable takes precedence. Never put a key in a command argument or tracked file.

DuckDuckGo uses its public HTML interface, not an official full-results API. This experimental connector stops on challenges, throttling, or unrecognized responses without bypassing them. Europe PMC uses its documented scholarly API. Both return at most five results per search, pace uncached queries, and cache results for seven days. Qwen gets at most three searches and four discovery responses per entry, plus one PDF extraction response. It can select only retrieved PDF links on allowed hosts. Publication identity, edition, and field interpretation remain unresolved until adjudicated; search results and model confidence cannot grant approval.

For the repository secret `DARTMOUTH_CHAT_API_KEY`, use the manual **Dartmouth citation research pilot** GitHub Actions workflow after it has been published to the default branch. It defaults to three entries, checks the exact model ID, restores fingerprint-matching baseline reviews, checkpoints attempts, and exports an evidence snapshot artifact. Model IDs and service availability are checked live; no alternate model or paid provider is selected automatically. The workflow caches local state between runs, including downloaded PDFs; GitHub caches can be evicted, so retain evidence separately when needed. Its artifact contains the portable snapshot, not PDF files. Secrets are passed only to the Dartmouth steps. No scheduled or pull-request run invokes the model. Use the deliberate retry input when revisiting failures with another backend or corrected configuration.

Dartmouth extraction asks the model to select numbered source passages; Python copies every quotation from the original text and validates its page and offsets. The extraction prompt excludes the input citation. Author assembly preserves source order, and conservative literal checks distinguish printed values from proposed interpretations. Publisher metadata from HTML head tags supplies PDF candidates before general search is needed. These checks establish where text came from, not whether it correctly describes the cited work; all model findings remain `needs_review`. Full GLM 5.3 uses maximum reasoning and a 16,000-token output budget. Its upstream model card specifies text input; the catalog's vision flag is not relied upon.

The [follow-up benchmark and live report](verification/benchmark/README.md) records a successful known publisher-page → PDF → Qwen run and 60/60 offline metadata checks across 30 real entries and deliberate alterations. This selected sample does not establish bulk-review accuracy. The [earlier pilot](verification/dartmouth-live-pilot.md) records search challenges, stale links, throttling, and the invented quotation that motivated source-passage selection.

The [September 14 representative audit](verification/pilot50/README.md) records the refreshed free GLM model catalog, fifty assistant source checks compared against blind automated extraction, thirteen bibliography corrections, and the remaining evidence gaps. All fifty extraction comparisons match after targeted repairs; twenty citations were cleared by deterministic verification. The full offline resolver update brought the baseline to 1,957 verified and 4,465 unresolved entries. Its unchanged repeat made no requests and added no review records.

The [first September 15 follow-up](verification/resolution-2026-09-15/README.md) added conservative publisher-name, final-article identity, issue-label and Cambridge print-date rules, plus DOI-specific discovery checkpoints. That pass ended with **2,206 verified / 4,216 unresolved entries**.

The [latest local continuation](verification/completion-2026-09-15/README.md) reached **3,669 verified / 2,753 unresolved entries** after its completed correction, source-metadata, catalogue, and preprint batches. It applies source-backed pagination, title, volume, year, issue, DOI, author, journal, and publisher corrections; adds strict edition-level book verification; improves explicit-initial and punctuation comparisons; and reopens two entries with unadjudicated correction notices. All completed stages have a zero-request, zero-write repeat. Known DOI-linked notices, suffix evidence, and corroborated article coordinates survive entry edits and portable cache restores. Work toward the remaining entries is ongoing. The [earlier follow-up](verification/resolution-followup-2026-09-15/README.md) remains a dated historical report.

### Fallbacks and human review

The fallback order is:

1. Crossref DOI lookup, or bibliographic search when no DOI is available. If a supplied DOI is absent, a search can provide candidates but cannot silently replace it.
2. DataCite lookup for a DOI absent from Crossref; arXiv lookup when an arXiv identifier is present. These records are retained as evidence for review. Their version/date semantics are not treated as equivalent to Crossref journal metadata.
3. Automatic PubMed comparison through Europe PMC, followed by publisher front-matter checks for available open-access full text. See the automatic-review commands above.
4. Optional LLM-driven web search for the actual PDF, followed by local PDF text extraction and checks that quoted evidence occurs on the stated page.
5. Human source review. Missing identifiers, paywalls, scanned PDFs, uncertain editions, and unsupported metadata stay unresolved.

No LLM/search provider is enabled by default. Concrete Dartmouth Chat and OpenAI Responses API adapters are included, alongside the provider-neutral adapter contract. Configuration and the PDF evidence format are documented in [the verification design](docs/verification.md). To use an adapter you have configured:

```bash
python -m pip install -r requirements-research.txt
python bibcheck.py crossref research CiteKey --adapter /absolute/path/to/research-adapter \
  --allow-host publisher.example --allow-host repository.example
```

Research is explicitly invoked for unresolved entries. The adapter discovers a PDF; bibcheck downloads it only from allowed HTTPS hosts, saves its SHA-256 and extracted page text, and validates page-specific quotations returned by the adapter. It never approves citations or edits BibTeX. This is evidence collection. The included OpenAI adapter performs real web search; other providers can implement the same contract.

For review without an adapter:

```bash
python bibcheck.py crossref review-packet CiteKey --output review-packet.json
```

The packet includes the exact entry, fingerprint, source candidates, and review instructions. Inspect the actual source and edition, correct the BibTeX when necessary, and rerun verification. If a human confirms the existing citation despite missing/conflicting metadata, record that decision using the fingerprint from the packet:

```bash
python bibcheck.py crossref approve CiteKey \
  --fingerprint HASH_FROM_REVIEW_PACKET \
  --reviewer 'Reviewer name' \
  --source 'Authoritative source URL or physical edition' \
  --note 'Fields and edition checked; explanation of any source discrepancy'
```

The command rejects stale fingerprints. LLMs must not use this command to impersonate human review. `attach-evidence` can retain externally collected JSON findings, but leaves the entry unresolved.

## Formatting, comparison, and commits

```bash
python bibcheck.py verify --fname cdl.bib --verbose
python bibcheck.py compare original.bib revised.bib --verbose
python bibcheck.py commit --verbose
```

Unlike `crossref verify`, `verify` and `commit` take the filename through `--fname`. `verify` checks the format and then the citations of new/edited entries (see [Suggested workflow](#suggested-workflow)); `verify --no-citations` is the format-only check. Formatting checks include citation-key conventions, author/editor formatting, duplicate detection, sentence case, page ranges, and lookup-table normalization of venues, publishers, and addresses. The allowed fields are listed in [keep_fields.txt](bibcheck/keep_fields.txt); DOI is supported. The accuracy checker can read additional fields, but unsupported fields remain unresolved. The formatter may reject/prune those fields unless its `force` override is present.

Citation keys use the first four letters of the first author's surname and the last two digits of the year, with the second surname for two-author works or `Etal` for larger author lists (for example, `Mann21`, `MannKaha21`, `MannEtal21`). Collisions receive letter suffixes. Multiword surnames should be brace-protected, and author names separated with ` and `. Page ranges use `--`.

The formatter is heuristic. In particular, passing formatting does not ensure correct capitalization after a colon; protected words and the formatter's `A` special case can retain capitals. Preserve proper nouns and acronyms deliberately and review titles against their sources. Duplicate detection uses surnames and title rather than publication version, so inspect proposed duplicate removals carefully.

The `force` field bypasses parts of legacy formatting/pruning; it does **not** certify a citation or bypass Crossref checks. It should not be used to conceal an accuracy finding.

To inspect proposed automatic formatting corrections without overwriting the source:

```bash
python bibcheck.py verify --fname cdl.bib --autofix --verbose --outfile cleaned.bib --no-citations
```

Review `cleaned.bib` before replacing `cdl.bib`. The legacy `magic` command overwrites the bibliography and attempts a commit; prefer the explicit review workflow. The `commit` command runs the `verify` gate, compares with the remote `master` bibliography for the message, and commits only the bibliography file (`git commit -- <file>`, without a shell), so other modifications are never included. It does not push. `verify` and `commit` exit nonzero on failure (1 for format or unresolved citations, 2 for a configuration or provider error).

## Using the bibliography in LaTeX

Copy or link `cdl.bib` into a project and use the bibliography style required by your manuscript:

```tex
\bibliographystyle{plain}
\bibliography{cdl}
```

For traditional BibTeX compilation:

```bash
pdflatex manuscript
bibtex manuscript
pdflatex manuscript
pdflatex manuscript
```

For command-line access to one shared local bibliography, add its directory to `BIBINPUTS` in your shell configuration. The trailing colon preserves TeX's default search locations:

```bash
export BIBINPUTS="$HOME/CDL-bibliography:$BIBINPUTS:"
```

With MacTeX/TeXShop, a personal TeX tree also works for GUI applications that do not inherit shell configuration:

```bash
mkdir -p "$HOME/Library/texmf/bibtex/bib"
ln -s "$HOME/CDL-bibliography/cdl.bib" "$HOME/Library/texmf/bibtex/bib/cdl.bib"
```

Adjust paths for your checkout. Keep a reviewed copy of the bibliography with a submission so later edits to the shared library do not change that submission's references.

## Using the bibliography on Overleaf

Upload `cdl.bib` to your project, or use Overleaf's [Add from External URL](https://docs.overleaf.com/managing-projects-and-files/adding-files-to-a-project/adding-a-file-from-a-url) with the [raw bibliography](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib). Refresh a linked file explicitly when you intend to take updates, then check the resulting citations.

Overleaf projects cannot contain Git submodules; the earlier instructions for adding this repository as a submodule inside an Overleaf project were incorrect. See [Overleaf's GitHub synchronization limitations](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/github-synchronization). If using GitHub synchronization, include an actual `cdl.bib` file in the project.

## Development

```bash
python -m pip install pytest
python -m pytest -q tests
python bibcheck/test.py
```

The regression suite uses local fixtures and fake services; it does not contact Crossref. It covers entry parsing, metadata disagreements, cache invalidation, retries, resumability, stale human approvals, and optional research evidence handling. Live verification is a separate, checkpointed operation.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [the verification design](docs/verification.md).

## Acknowledgements

This bibliography grew from a collection authored by Michael Kahana's [Computational Memory Lab at the University of Pennsylvania](https://memory.psych.upenn.edu/). It is maintained independently, with contributions from [members of the Contextual Dynamics Lab](https://github.com/ContextLab/CDL-bibliography/graphs/contributors).
