# Bibliography verification records

As of September 29, 2026, **6,377** of the **6,384 entries** in `cdl.bib` are verified: **6,361** have status `metadata_verified` and **16** have status `human_verified`. The other **7** are `needs_review` and are waiting for the user's review: see [2026-09-29-user-review/REVIEW.md](2026-09-29-user-review/REVIEW.md). An attribution audit on September 29 revoked twelve approvals that had been recorded in the user's name without the user approving the applied text; the research route then verified eight of them. The same audit found six rules recorded as the user's that were Claude's; they are listed in the decision log under "Rules Claude adopted (awaiting user confirmation)", with yes/no questions in [2026-09-29-user-review/CONFIRM.md](2026-09-29-user-review/CONFIRM.md). The rules used to decide each case (cite as printed, no conference abstracts, drop what can't be verified or stays ambiguous) are in the [decision log](resolution-plan-2026-09-22/README.md).

- [Current baseline](baseline.jsonl.gz): the saved result and evidence for every entry. `python bibcheck.py crossref restore verification/baseline.jsonl.gz` loads it into a local database; the pull request check reads it from the base branch.
- [Revoked approvals](revocations.jsonl): every human approval withdrawn with `crossref revoke`, recording who, when, why, and which approval. Restoring any snapshot keeps them revoked.
- [Key renames](key-renames.json) and [key deletions](key-deletions.json): every citation key that was renamed or removed during verification, with the reason. Check these if a paper's `\cite` key stops resolving.
- [Historical policy-1 baseline](baseline-policy1.jsonl.gz): the first Crossref pass (805 accepted / 5,617 unresolved). It can't approve anything under the current policy.

```bash
export CROSSREF_MAILTO='your.name@dartmouth.edu'
python bibcheck.py crossref restore verification/baseline.jsonl.gz
python bibcheck.py crossref status cdl.bib
```

A result applies only to an entry whose text matches exactly; editing an entry sends it back through verification. "Verified" means the entry agrees with the published record, not that the record itself is free of errors.

## How the library got here

The folders in this directory are dated working records, kept as an audit trail. In rough order:

1. **First Crossref pass and automatic review** (September 9–17): Crossref, PubMed/Europe PMC, publisher full text, catalogues and preprint servers. See [automatic-review.md](automatic-review.md), [resolution-2026-09-15](resolution-2026-09-15/README.md) and [completion-2026-09-15](completion-2026-09-15/README.md). This stage ended at 3,526 verified and 2,896 unresolved entries.
2. **New sources and rules** (September 22–25): DataCite, the ACL Anthology, PsyArXiv (through the OSF API), the Society for Neuroscience abstract archive, and the lab's decision rules. See [phase0-2026-09-22](phase0-2026-09-22/), [routes-2026-09-25](routes-2026-09-25/) and [machinery-2026-09-25](machinery-2026-09-25/).
3. **Research waves** (September 24–27): the entries no automatic source could settle were researched one at a time. Each field was matched to a quotation from an official source, then checked independently and reviewed. See [research-pilot-2026-09-24](research-pilot-2026-09-24/), [research-2026-09-25](research-2026-09-25/), [resolution-2026-09-26](resolution-2026-09-26/) and [resolution-2026-09-27](resolution-2026-09-27/).
4. **Applying the results** (the `apply-*` folders): each batch of corrections was applied, re-verified, and tested before it was committed. The [research route](research-route-2026-09-27/README.md) records the research evidence as verification results.

The [benchmark](benchmark/README.md) and [PDF benchmark](pdf-benchmark/) measure the checker against real entries and deliberately altered copies. See the [README](../README.md) and the [design documentation](../docs/verification.md) for commands and acceptance rules.
