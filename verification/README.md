# Bibliography verification records

This folder holds the lab's saved verification results for `cdl.bib` and the logs that go with them.

- [baseline.jsonl.gz](baseline.jsonl.gz): the saved result for every entry, with its evidence. Entries verified from quoted evidence carry the quotation and source URL for each field. `python bibcheck.py crossref restore verification/baseline.jsonl.gz` loads it into a local database, and the pull request check reads it from the base branch.
- [check_ci.py](check_ci.py): the script the `Citation verification` workflow runs.
- [key-renames.json](key-renames.json) and [key-deletions.json](key-deletions.json): every citation key that was renamed or removed, with the reason. Check these if a paper's `\cite` key stops resolving.
- [revocations.jsonl](revocations.jsonl): every human approval withdrawn with `crossref revoke`. Restoring any snapshot keeps them revoked.
- [benchmark/](benchmark/README.md) and [pdf-benchmark/](pdf-benchmark/README.md): the checker run against real entries and deliberately altered copies. `tests/test_discovery_review.py` runs the first; `tests/test_pdf_evidence.py` runs the second when the local paper library is mounted.

```bash
export CROSSREF_MAILTO='your.name@dartmouth.edu'
python bibcheck.py crossref restore verification/baseline.jsonl.gz
python bibcheck.py crossref status cdl.bib
```

A result applies only to an entry whose text matches exactly; editing an entry sends it back through verification. "Verified" means the entry agrees with the published record, not that the record itself is free of errors.

The rules used to decide each case are in the [decision log](../docs/decision-log.md). The dated working records of the September 2026 check (research, resolution and apply batches, review pages, audits and earlier baselines) are on the [`verification-records-2026-09`](https://github.com/ContextLab/CDL-bibliography/tree/verification-records-2026-09/verification) branch, which is never merged.
