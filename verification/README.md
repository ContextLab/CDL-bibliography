# Bibliography verification baseline

The latest completed **policy-2** stage covers all **6,422 entries**: **3,526 metadata matches** and **2,896 unresolved entries**, updated September 17, 2026. The [local completion run](completion-2026-09-15/README.md) records 792 source-backed bibliography edits, comparison fixes, and two reopened correction-notice cases and the repaired eight-entry suffix audit. Every completed positive stage passed a repeat with zero requests and zero new reviews. No human or LLM-based approvals were created. The full-library verification goal remains unfinished; source collection and further corrections continue. The [earlier follow-up](resolution-followup-2026-09-15/README.md) and [preceding pass](resolution-2026-09-15/README.md) remain historical reports.

The earlier automatic review extension resolved **1,047** of the 5,617 entries flagged by the first Crossref pass. See the [September 9 results](automatic-review.md) for that historical run. Fingerprints now use key-independent format v2 / snapshot schema 2: a key-only rename reuses approval; every other raw entry or dependency edit invalidates it.

- [Current baseline](baseline.jsonl.gz): complete evidence and statuses under policy 2.
- [Compact research queue](review-queue.jsonl.gz): current unresolved entries, fingerprints, and research routes.
- [Historical policy-1 baseline](baseline-policy1.jsonl.gz): original 805 accepted / 5,617 unresolved result; it cannot grant current policy-2 approval.

```bash
python bibcheck.py crossref restore verification/baseline.jsonl.gz
python bibcheck.py crossref verify cdl.bib --auto-review
```

Set `CROSSREF_MAILTO` before network use. Restore accepts matching fingerprints only. Exit 1 is expected while unresolved entries remain. Subsequent unchanged runs reuse their completed review stages; edits invalidate the associated results automatically.

The current baseline matches all keys, fingerprints, and statuses in the local report; SQLite integrity passed. Metadata agreement is evidence of source consistency, not an absolute accuracy guarantee. The optional paid LLM/PDF batch layer is implemented but has not been live-run.

The refreshed free Dartmouth adapter defaults to full GLM 5.3 and checks live free eligibility before inference. Its fifty source-extraction comparisons matched the assistant's recorded audit after three failed calls were retried and one omitted publisher metadata section was retrieved. This tests extraction from available sources, not certification of fifty citations or unattended retrieval. See the [pilot report](pilot50/README.md) and the earlier [benchmark](benchmark/README.md).

The baseline and compact queue contain matching current fingerprints. Resolver revisions revisit unresolved evidence once; repeated unchanged runs do not create fresh review records.

See the [README](../README.md) and [design documentation](../docs/verification.md) for commands and acceptance rules.
