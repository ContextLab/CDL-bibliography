# Dartmouth Qwen live pilot

This is the initial pilot record. See the [September 10 follow-up](benchmark/README.md)
for source-passage extraction, the successful publisher-to-PDF run, and benchmark results.

Tested September 9–10, 2026. This was a bounded debugging exercise, not a bulk
citation review. The bibliography and production verification database were not
modified by the pilot.

## Results

| Check | Observed result |
| --- | --- |
| Credential | Desktop key copied to ignored `.bibcheck/secrets/dartmouth_chat_api_key.txt`; directory mode 700, file mode 600. No key occurrences in Git-visible files. |
| Authentication and model discovery | Successful. Actual model ID: `qwen.qwen3.5-122b`. |
| Model-directed search | Successful Qwen search actions and real Europe PMC results; Qwen selected the correct El-Solh article's PDF source. |
| DuckDuckGo availability | Earlier standalone search succeeded; model-directed requests encountered HTTP 202 challenges and stopped. |
| Biomedical PDF retrieval | Publisher's supplied link returned 404; Europe PMC's PDF endpoint returned 429. Neither became citation approval. |
| Proceedings PDF retrieval | Actual “Attention Is All You Need” PDF downloaded successfully from `papers.nips.cc`. |
| Default/greedy extraction attempts | Initial 90-second timeout; later requests returned HTTP 400 containing an upstream hosted-vLLM 502 gateway error. A longer client timeout alone did not resolve this. |
| Direct-response extraction | HTTP 200, 1,168 prompt tokens, 516 completion tokens, zero reasoning tokens. Tested on the first page with an explicitly supplied, previously retrieved PDF URL. |
| Evidence acceptance | Rejected: the author quotation included an invented ellipsis. No research approval recorded. |

The successful extraction response proposed title, authors, year, booktitle and
entry type. Four proposed quotations existed on the supplied page; the author
quotation did not. Quotation presence is not equivalent to supporting the value:
the model explicitly acknowledged inferring the proceedings-series title from
the conference name. It correctly reported that volume, page range, DOI and
other absent fields could not be extracted from the supplied page.

The first-page extraction probe skipped discovery and is not a successful
end-to-end search-to-accepted-evidence run. Model-directed search and extraction
were demonstrated separately. Larger batches are not justified by this sample.

## Changes from debugging

- Corrected the default model ID using the live model listing.
- Added local key-file support; the environment variable takes precedence.
- Preserved all supplied PDF alternatives instead of dropping everything after
  the first link. At most three supplied copies of the selected record may be
  tried, with failures retained; a throttled host is not immediately retried.
- Accepted Markdown presentation fences around JSON while rejecting duplicate
  JSON keys, trailing prose, and multiple answers.
- Added restricted local diagnostics and an isolated first-page extraction mode.
- Tested [Qwen's documented direct-response settings](https://huggingface.co/Qwen/Qwen3.5-122B-A10B)
  through Dartmouth: `chat_template_kwargs.enable_thinking=false`, temperature
  0.7, top-p 0.8, top-k 20 and presence penalty 1.5. The successful response
  reported zero reasoning tokens. These settings do not guarantee accuracy.

Validation: 145 regression tests pass, Ruff passes for the changed Python files,
the Actions workflow passes actionlint, and `git diff --check` passes. Existing
dependency deprecation warnings remain.

## Reproduction and evidence

```bash
python bibcheck/dartmouth_research_adapter.py --check-model
python verification/dartmouth_pilot.py --key ElSo18 --backend europepmc
python verification/dartmouth_pilot.py --key VaswEtal17 \
  --source-url https://papers.nips.cc/paper/7181-attention-is-all-you-need.pdf \
  --pages 1
```

Local, ignored diagnostics for the direct-response extraction are under
`.bibcheck/debug/dartmouth-61lbqdh9/`: the downloaded PDF, extracted first page,
sanitized model response, and the failed quotation check. Debugging responses
are not promoted to the production verification cache. The repository contains
the reproducible pilot script and this summary, not the key or raw diagnostics.

Qwen is usable for bounded evidence gathering. Automatic approval remains
disabled: the observed author-quotation error and inferred field value show why
model confidence and quotation existence alone are insufficient.
