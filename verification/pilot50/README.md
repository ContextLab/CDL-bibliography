# Representative citation audit — September 14, 2026

Follow-up: the [latest local continuation](../completion-2026-09-15/README.md) brings this pilot to **40/50 verified**, including AherBeat81 through its reviewed original book edition and LOC imprint record. Ten remain unresolved. The findings and counts below record the original September 14 audit.

The assistant inspected all fifty selected source records before the model batch and recorded the expected findings. After correcting one missing source section and retrying three failed calls, **50/50 extraction comparisons match**: 446 populated fields and 54 explicit unknowns. These are source-extraction results, **not fifty verified citations**. The deterministic verifier cleared **20/50**; **30 remain `needs_review`**.

Thirteen bibliography entries were corrected locally. Two exact journal-name mappings cleared seven more pilot entries and another 85 entries in an offline backlog pass. The complete library is now **1,957 metadata-verified / 4,465 needs-review**, with no pending/provider-error entries. No model output granted approval and no human approval was impersonated. Nothing was pushed.

## Evidence and scope

- [Frozen sample](manifest.json): fifty of the 790 entries with one remaining blocker and a Crossref title/author match. One example of each of fifteen blocker categories, then proportional largest-remainder allocation; deterministic SHA-256 ordering within categories. This is not a representative sample of all 4,570 originally unresolved entries.
- [Assistant audit ledger](manual-ledger.txt): individually recorded author signatures, year, volume, issue, pagination and source interpretation. [Expected fields](expected.json) were written before the model extractions; their original hash is recorded with each successful call.
- [Exact comparisons and model traces](results.json): actual model values, comparison outcomes, source kinds and hashes. [Backlog changes](backlog-results.json) lists the additional 85 resolved keys.
- [Refreshed Dartmouth catalog](dartmouth-models.json): sanitized public model metadata; private upstream configuration and credentials are excluded.

The source package contains 38 Europe PMC indexed records, six original article XML documents supplementing those records, three publisher HTML-head records, one fetched proceedings PDF, and eight primary-page/PDF excerpts retrieved with assistant help. The Kerby page required a separate article-information excerpt. Source collection was assisted when publishers blocked scripted retrieval. This does **not** establish unattended retrieval of fifty complete papers or independent human certification.

Comparison preserves exact bibliographic content after documented typography normalization: case, LaTeX typography, a terminal period, and spacing/periods in author initials. Authors are compared as ordered compound surnames plus every given-name initial, retaining accents. This does not test expansion of initials into full given names. Actual source values and unknowns remain visible in `results.json`; no fuzzy score is used. The production verifier separately retains its stricter full-name checks when citations supply full names.

Raw source documents and the content-addressed model cache remain in ignored `.bibcheck/pilot50/`. No abstracts, full articles, API keys or SQLite databases are added to Git by this pilot.

## Model selection and live failures

Full **`zai-org.glm-5.3`** is the selected free text model. Dartmouth lists it and Flash as **Local**, with zero input/output cost. Dartmouth explicitly says [Local models are free](https://rc.dartmouth.edu/ai/online-resources/understanding-tags/). Selection was informed by the [full GLM model card](https://huggingface.co/zai-org/GLM-5.3) and [Flash model card](https://huggingface.co/zai-org/GLM-5.3-Flash); this is not a controlled comparison against every free model on this citation task.

Full GLM uses maximum reasoning, temperature 1, top-p 0.95, and a 16,000-token output budget. The full model's documented input is text, despite Dartmouth reporting a vision capability. We do not rely on that vision flag. Both the manual workflow and adapter now default to full GLM. Each adapter invocation confirms live availability and free eligibility before inference. Explicit nonzero or malformed prices reject a model even if tagged Local/Free; no paid fallback is selected.

The first pass produced 46 matching results, one source-coverage disagreement, one malformed JSON response (`BuscEtal08`), and two 240-second timeouts (`ZekvEtal18`, `MillMcGi52`). The malformed output and timeouts were not accepted. All three succeeded on explicit retry. For `Kerb14`, the model correctly withheld volume because the first saved web excerpt stopped before the article-information section. The assistant's separate source check had found volume 3 there. Retrieving that section changed the source hash and triggered one new extraction, which agreed. The expected answer was not changed to fit the model. Earlier outputs/errors remain in the local cache.

There were 54 batch inference attempts (plus the earlier synthetic smoke test). Repeating the completed audit offline, with credentials explicitly unavailable, made **zero model calls**.

## Local corrections and remaining work

The thirteen corrected keys are `Lang05`, `HuebWill18`, `Scha03`, `KuhlEtal07`, `VidoEtal15`, `WyliEtal07`, `RoteEtal09`, `ZekvEtal18`, `MonaEtal07`, `BuscEtal08`, `WaydEtal06`, `WickNorm66`, and `Cowa00`. Changes address a wrong journal, volume, issue, years, incomplete page ranges, article locators, a DOI misplaced as pagination, and a book chapter misclassified as an article. The old Wylie and Cowan keys are retained with the existing `Force` formatting exception to preserve manuscript references. `Force` does not bypass source verification; a regression test checks that a wrong year still fails.

The two venue mappings enumerate PNAS title variants and *The Journal of Neuroscience* title variants. They do not alter paper titles or collapse similarly named journals. Resolver revision 2 reconsiders unresolved cached evidence once; accepted entries retain their original approval and check time. No general publisher-name equivalence or relaxation of version/date checks was introduced.

| Remaining pilot group | Count | Required next evidence or rule |
| --- | ---: | --- |
| Publisher / historical imprint | 16 | Original article or issue front matter establishing the publisher at publication time; any reusable imprint mapping must be dated and source-backed. Current host branding is insufficient. |
| Publication year | 4 | Publisher issue metadata for Miller, Takane and Cohen; original issue/PDF for the Crossref-versus-PubMed disagreement on Wiggs. Model date interpretation alone cannot approve them. |
| Linked preprints | 3 | A narrowly tested rule establishing the cited final article from its own DOI and complete journal coordinates while retaining the separate preprint relationship. |
| Proceedings names | 2 | Exact official proceedings-title evidence and controlled venue-name handling. The Carver PDF supplies the formal header; the Tian source still lacks complete proceedings pagination. |
| Explicit erratum | 1 | Read the linked Bruns erratum and document its effect before adjudication. |
| Issue label | 1 | Support PubMed's `Pt 7` versus publisher issue `7` with a tested field-specific rule. |
| Publisher address / organization | 2 | Establish the field's role; an author affiliation must not become a publisher address, and a publisher must not silently become an organization. |
| Missing pagination / locator | 1 | Obtain Kerby's explicit article locator from an authoritative metadata export or original article; do not infer it from DOI digits. |

The pilot demonstrates that structured metadata corrections and small source-backed rules scale better than repeatedly asking a model to approve every citation. Model/source research remains useful for the unresolved groups, with cached outcomes and explicit evidence gaps.

## Reproduce locally

From the repository root, using the existing local evidence cache:

```bash
# Free model catalog and API check; requires the existing local key or environment key.
.venv/bin/python bibcheck/dartmouth_models.py .bibcheck/dartmouth-models.json
.venv/bin/python bibcheck/dartmouth_research_adapter.py --check-model

# No network/model/key needed once the local source and extraction cache exists.
.venv/bin/python verification/pilot50/audit.py --offline

# Resume only uncached inputs; explicitly retry failed calls when intended.
.venv/bin/python verification/pilot50/audit.py --retry-errors

# Recheck the sample and assert an unchanged repeat makes zero requests.
.venv/bin/python verification/pilot50/verify_local.py

# Full ordinary validation (unresolved citations deliberately keep source-check exit 1).
.venv/bin/python -m pytest -q tests --disable-warnings
.venv/bin/python verification/benchmark/run.py
.venv/bin/python bibcheck.py verify --fname cdl.bib
.venv/bin/python bibcheck.py crossref verify cdl.bib --auto-review
```

The frozen selection and collected-source scripts document this particular run. `collect.py --report PATH` accepts an explicit original report and retains prior source records; it does not overwrite existing evidence with a newer bibliography's judgments. Raw source bytes are required to rerun the content-addressed extraction cache and are not distributed in this Git artifact. `results.json` and `expected.json` retain the portable comparison evidence.

Validation: **200 tests passed**, **60/60 documentary benchmark cases passed**, formatting/duplicate validation passed, and SQLite quick-check passed. The first corrected sample check used fourteen registry requests; its unchanged repeat used zero. Rechecking the two formatting-exception edits used cached source responses and zero requests. The offline backlog pass added 85 approvals; repetition added zero review records and preserved every prior approval.
