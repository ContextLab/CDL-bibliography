# Bibliography verification baseline

The current **policy-2** baseline contains all **6,422 entries** checked on September 9, 2026: **1,852 metadata matches** and **4,570 unresolved entries**. There are no pending entries or provider errors. No BibTeX was edited and no human approvals were recorded.

The automatic review extension resolved **1,047** of the 5,617 entries flagged by the first Crossref pass. See the [automatic-review results](automatic-review.md) for the evidence routes, remaining queue, validation, and limitations.

- [Current baseline](baseline.jsonl.gz): complete evidence and statuses under policy 2.
- [Compact research queue](review-queue.jsonl.gz): current unresolved entries, fingerprints, and research routes.
- [Historical policy-1 baseline](baseline-policy1.jsonl.gz): original 805 accepted / 5,617 unresolved result; it cannot grant current policy-2 approval.

```bash
python bibcheck.py crossref restore verification/baseline.jsonl.gz
python bibcheck.py crossref verify cdl.bib --auto-review
```

Set `CROSSREF_MAILTO` before network use. Restore accepts matching fingerprints only. Exit 1 is expected while unresolved entries remain. Subsequent unchanged runs reuse their completed review stages; edits invalidate the associated results automatically.

The current baseline matches all keys, fingerprints, and statuses in the local report; SQLite integrity passed. Metadata agreement is evidence of source consistency, not an absolute accuracy guarantee. The optional paid LLM/PDF batch layer is implemented but has not been live-run.

The free Dartmouth Qwen adapter has since completed bounded live probes. See
the [benchmark and follow-up report](benchmark/README.md); model evidence remains
unresolved and is not a human approval. The local database also contains later
discovery checkpoints absent from this September 9 baseline.

Baseline SHA-256: `2ae677abc4077b8d40829ef177dc10138fa63b22a47afc1481448c1a3bc9a28d`.

See the [README](../README.md) and [design documentation](../docs/verification.md) for commands and acceptance rules.
