# Bibliography verification records

This folder holds the lab's saved verification results for `cdl.bib` and the logs that go with them.

- [baseline.jsonl.gz](baseline.jsonl.gz): the saved result for every entry, with its evidence. Entries verified from quoted evidence carry the quotation and source URL for each field. `cdlbib crossref restore verification/baseline.jsonl.gz` loads it into a local database, and the pull request check reads it from the base branch.
- [baseline-additions.jsonl](baseline-additions.jsonl): the saved results of entries verified since `baseline.jsonl.gz` was written, as text with one result per line after a header line. `cdlbib crossref restore verification/baseline.jsonl.gz` reads it together with the snapshot, and the pull request check reads both from the base branch. The `Citation verification` workflow adds to it after a push to `master` that passes; writing a whole snapshot with `cdlbib crossref snapshot` empties it.
- [check_ci.py](check_ci.py): the script the `Citation verification` workflow runs.
- [key-renames.json](key-renames.json) and [key-deletions.json](key-deletions.json): every citation key that was renamed or removed, with the reason. Check these if a paper's `\cite` key stops resolving. Every key follows the key rule in the [README](../README.md#verify), with no exceptions.
- `approvals.jsonl` (created by the first `cdlbib send` that shares an approval): one line per human approval sent with `cdlbib send`, appended and never rewritten. A line holds the key, the entry's fingerprint, the review (reviewer, GitHub login and id, source, note), the time it was recorded, the policy version and the review's digest. The checker reads an entry as `human_verified` when a line has the entry's current fingerprint and is not revoked; no restore is needed. The pull request check reads this file from the base branch, and counts the lines a pull request adds only when someone with write access to the repository vouches for them.
- [revocations.jsonl](revocations.jsonl): every human approval withdrawn with `crossref revoke`. Restoring any snapshot keeps them revoked, and a revocation takes precedence over a line in `approvals.jsonl`.
- [benchmark/](benchmark/README.md) and [pdf-benchmark/](pdf-benchmark/README.md): the checker run against real entries and deliberately altered copies. `tests/test_discovery_review.py` runs the first; `tests/test_pdf_evidence.py` runs the second when the local paper library is mounted.

```bash
export CROSSREF_MAILTO='your.name@dartmouth.edu'
cdlbib crossref restore verification/baseline.jsonl.gz
cdlbib crossref status cdl.bib
```

A result applies only to an entry whose text matches exactly; editing an entry sends it back through verification. "Verified" means the entry agrees with the published record, not that the record itself is free of errors.

The rules used to decide each case are in the [decision log](../docs/decision-log.md). The dated working records of the September 2026 check (research, resolution and apply batches, review pages, audits and earlier baselines) are on the [CDL-bibliography-stacks](https://github.com/ContextLab/CDL-bibliography-stacks/tree/main/verification) archive repository, which is never merged.
