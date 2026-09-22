# Automatic bibliography review — September 9, 2026

This page records the September 9 run. The linked baseline/queue have since been updated; see the [current status](README.md) and [September 14 pilot](pilot50/README.md).

The free automated layers resolved **1,047 of the 5,617 originally flagged entries** (18.6%), without editing `cdl.bib` or recording any human approvals. **1,852 of 6,422 entries** now have supported metadata matches; **4,570 remain unresolved**. These remaining entries are an evidence/research queue, not 4,570 confirmed errors and not a claim that they each require manual review.

| Evidence route | Accepted entries |
| --- | ---: |
| Crossref under policy 2 | 1,639 |
| PubMed/Europe PMC adjudication | 212 |
| Publisher front matter from actual PMC full text | 1 |
| Total | 1,852 |

The original policy-1 Crossref pass accepted 805. Offline reassessment resolved another 834 by separating optional issue-number completeness from disagreement, recognizing benign review/reference relations, and fixing ampersand handling. No original accepted entry was downgraded in this library. This is an explicit policy revision, not new external evidence for those 834 entries.

The second-source pass checked 4,225 DOI candidates in 170 paced batch requests, completing additional metadata review for 3,786 entries. It resolved 212 cases under documented field-specific rules. The full-text pass checked 194 entries with 194 total requests, reusing pilot downloads, and resolved one further case (`ElSo18`): the publisher article and PubMed support volume 10, where the registry deposit did not match. The other full-text findings remain available as evidence; retrieving a document alone is not approval.

## Current artifacts

- [Current policy-2 baseline](baseline.jsonl.gz): all 6,422 entries, statuses, fingerprints, source records, and field evidence.
- [Compact unresolved queue](review-queue.jsonl.gz): the current unresolved entries, fingerprints, research routes, findings, and candidate URLs. Candidate URLs are discovery leads, not confirmed corrections.
- [Original policy-1 baseline](baseline-policy1.jsonl.gz): historical audit, not restorable as current approval under policy 2.
- `.bibcheck/verification.sqlite3`: local indexed review history and response cache.
- `.bibcheck/report.jsonl`: detailed current local report.

The current baseline matches every report key, fingerprint, and status. SQLite integrity check passed. Static queue/baseline files are point-in-time artifacts; use the CLI on the current bibliography after edits.

## Remaining queue

These mutually exclusive groups choose one closest retrieved candidate for triage only; they do not decide whether a citation is correct.

| Next research route | Entries |
| --- | ---: |
| author identity | 1,084 |
| field adjudication | 1,194 |
| publication version | 353 |
| source discovery | 1,939 |

## Reuse and next automation

```bash
# One command for Crossref plus all free automatic layers.
python bibcheck.py crossref verify cdl.bib --auto-review

# Or run the free layers individually.
python bibcheck.py crossref auto-review cdl.bib
python bibcheck.py crossref fulltext-review cdl.bib

# Restore shared results in another clone, accepting current fingerprints only.
python bibcheck.py crossref restore verification/baseline.jsonl.gz
```

Set `CROSSREF_MAILTO` before network use. The normal verification audit and repeated automatic metadata/full-text commands each made zero network requests once their work was complete. Accepted results were also rechecked offline from saved source evidence. Exit 1 is expected while unresolved entries remain.

A concrete OpenAI web-search/PDF adapter and `research-batch` command are implemented. They discover an actual PDF on allowed hosts, download it, extract page text, and validate quoted field evidence. Use `--keys` to prioritize an active manuscript, and `--limit` to bound a batch. Failed/completed attempts are checkpointed so ordinary repeats do not rebill them. Three consecutive failures stop the batch.

**No paid LLM batch was run.** The model/provider preference has not been supplied. The adapter has offline protocol tests; live provider/model compatibility and actual cost remain to be measured in a small pilot. Request/token caps are not a dollar budget. The optional commercial layer never runs as part of the free commands. Model confidence or quotations alone do not grant `human_verified` status.

Corrections and unresolved edition/identity conflicts should be presented as evidence-backed proposals. Human decisions should be needed where source identity, intended version, inaccessible material, or contradictory evidence cannot be resolved automatically; this implementation does not promise that the remaining queue can all be cleared without judgment.

## Validation

- 124 offline tests passed, including adversarial DOI/author/date/version cases, reference-list traps, cache migration/invalidation, batch resumption, and PDF/model evidence handling.
- Ruff passed for the verification/research code and tests.
- `git diff --check` passed.
- The earlier full-library formatting regression passed; no BibTeX or formatter code was changed in this automatic-review extension.
- Paid LLM/provider behavior has not been live-tested.

See the [README](../README.md) for setup and [verification design](../docs/verification.md) for exact acceptance boundaries and source documentation.
