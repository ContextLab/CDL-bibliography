# Bibliography verification records

As of September 30, 2026, every one of the **6,384 entries** in `cdl.bib` is verified: **6,348** have status `metadata_verified` and **36** have status `human_verified`, each recorded with the user answer it came from. No entry is left unresolved. An attribution audit on September 29 revoked twelve approvals that had been recorded in the user's name without the user approving the applied text; the research route then verified eight of them. The same audit found six rules recorded as the user's that were Claude's; the user answered them on September 30 (five confirmed, the surname rule replaced by the user's own: one source is sufficient, and a mismatch goes to the user), recorded in the decision log under "Rules Claude adopted, then confirmed or replaced by the user (2026-09-30)" and in [2026-09-29-user-review/CONFIRM.md](2026-09-29-user-review/CONFIRM.md). The rules used to decide each case (cite as printed, no conference abstracts, drop what can't be verified or stays ambiguous) are in the [decision log](resolution-plan-2026-09-22/README.md).

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

### Renamed apply folders (2026-09-29)

Eight `apply-*` folders were named with dates later than the day they were created. They
were renamed with `git mv` to the date of the commit that added them (`git log
--diff-filter=A --format=%ad --date=short -- <folder>`), with a letter for the second and later
folders of a day, in creation order. Every reference in code, tests, fixtures, JSON, docs and the
verification database was updated. The approval notes in the frozen test snapshot
`tests/fixtures/revocation/baseline-7f3eead-3-approvals.jsonl.gz` were updated too. Records
whose text changed carry a `path_migration` note that points here.

| Old name | New name | First commit |
|-|-|-|
| apply-2026-09-26 | [apply-2026-09-25b](apply-2026-09-25b/README.md) | 2026-09-25 |
| apply-2026-09-26b | [apply-2026-09-25c](apply-2026-09-25c/README.md) | 2026-09-25 |
| apply-2026-09-27 | [apply-2026-09-25d](apply-2026-09-25d/README.md) | 2026-09-25 |
| apply-2026-09-28 | [apply-2026-09-25e](apply-2026-09-25e/README.md) | 2026-09-25 |
| apply-2026-09-29 | [apply-2026-09-25f](apply-2026-09-25f/README.md) | 2026-09-25 |
| apply-2026-09-28-wave1 | [apply-2026-09-26-wave1](apply-2026-09-26-wave1/README.md) | 2026-09-26 |
| apply-2026-09-29-waves2-9 | [apply-2026-09-27-waves2-9](apply-2026-09-27-waves2-9/README.md) | 2026-09-27 |
| apply-2026-09-30-final | [apply-2026-09-27b-final](apply-2026-09-27b-final/README.md) | 2026-09-27 |

The [benchmark](benchmark/README.md) and [PDF benchmark](pdf-benchmark/) measure the checker against real entries and deliberately altered copies. See the [README](../README.md) and the [design documentation](../docs/verification.md) for commands and acceptance rules.
