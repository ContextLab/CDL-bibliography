# Citation verification benchmark

The pilot scripts (`verification/dartmouth_pilot.py`, `verification/discovery_pilot.py`) and
the dated reports this page cites are on the
[CDL-bibliography-stacks](https://github.com/ContextLab/CDL-bibliography-stacks/tree/main/verification/benchmark)
archive repository. `run.py`, `cases.json` and `results.json` are here; `tests/test_discovery_review.py`
runs the benchmark.

September 10, 2026. This is a reproducible check of documentary metadata
comparisons, with separate live retrieval/model probes. It is not a certification
of the bibliography or an estimate of production accuracy.

## Frozen metadata checks

[`cases.json`](cases.json) contains 30 real bibliography entries and one deliberate
perturbation per entry: 60 cases total. It retains retrieved documentary records
and source URLs, excluding saved comparison flags. The runner recomputes every
decision from those records without network requests or a model vote.

There are 25 matching controls, five controls that must remain unresolved, and
30 altered cases that must remain unresolved. Coverage includes subtitles and
colons, accented names, ordered authors, wrong years/pages/DOIs, publication
types, book editions, and preprint versus final-publication identity. The five
abstention controls are:

| Key | Why the available records do not authorize acceptance |
| --- | --- |
| `Thor13` | Book title, volume, and publisher differ from deposited edition metadata. |
| `FranLiu18` | Posted-content metadata does not establish final journal publication. |
| `BirdEtal09` | Retrieved candidates are reviews of the book, not the cited book. |
| `VaswEtal17` | Later posted-content copies do not establish the 2017 proceedings record. |
| `BateEtal15b` | Journal matching does not establish the cited preprint identity/version. |

Run from the repository root:

```bash
python verification/benchmark/run.py
```

[`results.json`](results.json): **60/60 pass**, with zero false acceptances and
zero missed matches relative to these fixture labels. All 35 expected blocks
remain blocked. This is a small, selected regression set. Its labels describe
support from frozen metadata, not independent human review of 30 PDFs; it does
not measure Qwen's extraction accuracy or establish a zero-error rate.

`build.py` deliberately refreshes fixtures from the local verification database.
It is not part of a normal test run. Review both evidence and labels before
replacing the frozen set. `base_fingerprint` identifies the original entry;
altered cases deliberately change its fields.

## Live source and model checks

The follow-up to the [earlier pilot](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/dartmouth-live-pilot.md) changed Dartmouth
extraction so Qwen selects numbered passages and Python copies their exact
text. The extraction prompt receives source text without the input citation.

| Probe | Observed result |
| --- | --- |
| *Attention Is All You Need*, proceedings PDF front page | Live Qwen returned title and eight individual authors with source IDs. The initial parser rejected repeated author items; after adding ordered author assembly, replaying the saved response passed all quotation checks. This was a replay after a fix, not a second live success. |
| UMAP, JOSS PDF front page | Live extraction completed and every selected quotation passed. An attached numerical affiliation marker exposed a literal-name boundary issue, now covered by a regression test. |
| UMAP, known JOSS landing page → PDF → Qwen | The current implementation completed with two successful HTTP 200 model calls, no search call, and all quotation checks passing. Only the proposed BibTeX entry type was classified as requiring interpretation. |

The complete run retrieved metadata from the actual
[JOSS publisher page](https://joss.theoj.org/papers/10.21105/joss.00861), selected
its supplied [PDF](https://joss.theoj.org/papers/10.21105/joss.00861.pdf), and
extracted the title, ordered authors, year, journal, volume, issue, article
number, and DOI. It starts with a known landing URL; it does not demonstrate
reliable general web discovery from a citation alone. Reproduce with local
credentials and the research dependencies installed:

```bash
python verification/dartmouth_pilot.py --key McInEtal18b \
  --landing-url https://joss.theoj.org/papers/10.21105/joss.00861 \
  --allow-host joss.theoj.org --allow-host www.theoj.org --pages 1
```

Diagnostics stay in ignored `.bibcheck/debug/`. These probes do not modify
the bibliography or production approvals. Literal text support cannot establish
that a passage describes the target work, that all authors were selected, or
that a year is a publication date. **All LLM/PDF findings remain `needs_review`.**
No PDF-based automatic acceptance rule was enabled by this benchmark.

## Expanded Crossref discovery pilot

[`discovery-pilot.json`](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/benchmark/discovery-pilot.json) records ten previously unresolved
entries: five preprints and five older journal citations. Each received one
focused title query with up to 20 Crossref candidates, using the existing paced
client and unchanged acceptance rules.

- Ten network requests; **zero newly verified entries**.
- Repeating the command made **zero network requests** because attempts were
  checkpointed.
- Queue after the pilot: **1,852 metadata verified; 4,570 needing review**.
- A selected candidate with the fewest reported issues is diagnostic only;
  it is not necessarily the correct work. Several candidates were unrelated.

The command is available as `crossref discover-review --limit 10`, with optional
`--keys` pointing to one citation key per line. The pilot's keys are recorded
in the JSON report and [repository manifest](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/benchmark/discovery-pilot-keys.txt). From the
repository root, `python verification/discovery_pilot.py` uses that manifest and
the configured contact (or the contact from an existing cached Crossref request).
An unresolved queue produces exit code 1 even when every
request completed normally. No BibTeX entries were edited.

The sample provides no evidence that repeating this expanded query across the
remaining queue would clear many entries. Further work should target identified
publisher/repository records and independently review more source-based cases
before expanding automatic acceptance.

## Local validation

The full test suite passed: 164 tests (with dependency deprecation warnings).
Ruff passed for the verification modules, tests, and pilot scripts; actionlint
and `git diff --check` also passed. A broader Ruff scan found 27 existing
findings in the unchanged formatter helper and notebook. A credential scan
found no occurrences of the local API key in Git-visible files. `cdl.bib`
remains unchanged.

The [September 11 source-text audit](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/benchmark/source-audit-2026-09-11.md) records a separate
inspection of the two cached front pages and the proceedings fields still
unsupported by that evidence. No new calls or approvals were made.

## Source-role cases

The [September 11 source-role audit](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/benchmark/source-role-audit-2026-09-11.md) adds the
negative cases the earlier audit called for. Six constructed selections, each a
wrong answer, previously reported `literal_text_present` with no unsupported
fields: a receipt date, a copyright notice and a preprint stamp each supplying a
different year for one front page, a title taken from a reference-list entry, an
affiliation read as a publisher, and a truncated author list.

Field evidence now carries a `role_risk` list, collected in `role_risk_fields`,
with every match also recorded as an explicit uncertainty. Replaying both cached
extractions through it flagged none of their thirteen fields. The flags never
approve and never block, and an empty list is not evidence that a role is
correct. No PDF acceptance rule was enabled.

## Proceedings record for `VaswEtal17`

The [September 14 proceedings-record note](https://github.com/ContextLab/CDL-bibliography-stacks/blob/main/verification/benchmark/proceedings-record-2026-09-14.md)
identifies the publisher record behind the entry whose series title, volume and
pagination the PDF front page could not establish. Crossref holds no DOI for
NeurIPS proceedings papers before 2019, and two queries returned only unrelated
works; the NeurIPS proceedings site supplies both a BibTeX record and a metadata
document, which together confirm the booktitle, volume 30, pages 5998–6008, year
and all eight ordered authors.

Those requests carried no `mailto` and so did not use the Crossref polite pool.
`PoliteClient` still requires a real contact, and bulk verification traffic is
unchanged. The finding is documentary evidence from one provider, not a human
review: `VaswEtal17` remains `needs_review`, its abstention fixture is unchanged,
and the citation's `@conference` type still blocks automatic comparison.
