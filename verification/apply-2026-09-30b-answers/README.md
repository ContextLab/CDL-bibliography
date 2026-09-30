# User answers of 2026-09-30, sections A, B and D (batch answers0930b)

The user answered the review page https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM (database
collection `review0930`) and wrote "i've answered all questions". The page's source, template,
build script and its notes-audit input are in
[../2026-09-30-user-review/page/](../2026-09-30-user-review/page/) (`build_page.py` still names
the notes-audit file by the session scratch path it was built from; the copy is
`page/notes-audit.json`). The 14 answer documents, read with the ArtifactData tool on 2026-09-30
(15:25 UTC), are in [answers/](answers/); no section C (surname) document existed then, and
section C is not applied here. What each answer was and what was done: decision log,
[resolution-plan README](../resolution-plan-2026-09-22/README.md), "User answers 2026-09-30
(review page)".

## What changed

- **cdl.bib:** only the two cite keys of the swap. The Psychological Review reply (doi
  10.1037/a0013724) is now KahaEtal08a; the chapter (doi 10.1016/b978-012370509-9.00185-6,
  title kept as printed) is now KahaEtal08b.
- **verification/key-renames.json:** three rows (commit `answers0930b`, with the user's note and
  the answer time) for the swap, through the temporary key `KahaEtal08-swap-2026-09-30`, so a
  reader that follows the log in order maps each work to its new key.
- **verification/key-deletions.json:** CronEtal94's row gains `confirmed_by` (doc
  note-CronEtal94, "Confirm the drop", 2026-09-30T14:39:09.996Z).
- **Approvals** (`bibcheck.py crossref approve`, reviewer "Jeremy Manning", current fingerprint):
  Bart32, KahaEtal24, Mink15, Youn61 (section A); ScotEtal07, KahaMill13, Hook69 (section D).
  Palm78 (D) was already `metadata_verified` and is recorded as resolved only. The section B
  "keep" answers (DougPeuc73, Mann06, Hint03, Murd71) change nothing.

## Checker fixes

1. **Tilde accent outside braces.** `I L Pi\~{n}a` (PollEtal00) and `A N\'{u}\~{n}ez`
   (NuneEtal87): BibTeX name splitting reads `~` as a space, so bibtexparser's `splitname`
   returned the surname `{n}a`. New [bibcheck/name_parsing.py](../../bibcheck/name_parsing.py):
   `splitname` braces each tilde accent at brace depth 0 (`\~{n}`, `\~n`) before splitting; every
   `bibcheck/` module now imports it instead of bibtexparser's.
2. **`\aa`.** `E Id{\aa}s` (MagnEtal98) and `S-{\AA} Christianson` (Chri92, editor):
   `verification.normalized` rejected `\aa`/`\AA` as unknown commands; they are now known
   (å, Å).

Tests: [tests/test_name_parsing_2026_09_30.py](../../tests/test_name_parsing_2026_09_30.py), on
the author fields frozen from cdl.bib and the Crossref author records fetched 2026-09-30, with
negative controls (a bare `~` tie still splits; braced accents are left as written; other names
split exactly as before; a different surname, `Pina` or `Idas`, still differs; `\aaa`, `\ab`
and `\foo` are still rejected; NuneEtal87's garbled Crossref "Nu´n˜ez" still differs).

Library effect ([parser_scan.py](parser_scan.py), [parser_diff.py](parser_diff.py),
[parser-fix-effect.json](parser-fix-effect.json)): every saved result (6,384) re-derived offline
from its saved evidence, once with the code of 33905aa and once with the fix, 0 requests, 0
writes. **No entry changes status.** Only four entries contain either pattern (PollEtal00,
NuneEtal87, MagnEtal98, Chri92); all four were and stay `metadata_verified`. One re-derivation
differs: MagnEtal98 now verifies on its Crossref record directly (with the code of 33905aa the
re-derivation did not verify it, and its research-evidence approval was kept); in the production pipeline its accepted
source moved from research evidence to Crossref, status unchanged. PollEtal00 still verifies on
research evidence (its Crossref comparison has other findings).

## A revocation defect found and fixed during this batch

The first run ([attempt1.log](attempt1.log)) stopped at its own negative control: replaying
ScotEtal07's revoked approval, as `verification/revocations.jsonl` shows it, was **accepted**.
Cause: commit 856d637 (folder renames) rewrote the approval notes of eleven ledger rows
(`apply-2026-09-28` → `apply-2026-09-25e`) but kept each row's `approval_digest`, so the ledger's
approval text no longer hashed to the recorded digest, and `approve` and `Cache.get` compared
the recorded digest only. Fix: `verification.revoked_digests` (a revocation revokes its recorded
digest and the digest of the approval text it carries), used by `revocation_matches` and
`approve`; `Cache.revocations` keeps both the database's and the ledger's copy when they differ;
`approve` drops the "Human approval revoked" notice from a new approval's issues. Test:
`test_ledger_copy_edited_after_revocation_is_still_revoked` in tests/test_revocation.py. The
accepted replay stays in the database's append-only history (row after ScotEtal07's first new
approval); with the fix it reads as revoked, and the resumed run recorded ScotEtal07's new
approval again (1 write), which is the current result.

## Run

    python verification/apply-2026-09-30b-answers/apply.py --apply
    python verification/apply-2026-09-30b-answers/restore_check.py <new empty database path>

[apply.py](apply.py) (frozen inputs: [answers0930b-batch.json](answers0930b-batch.json) and
[answers/](answers/)) stages the swap in a copy (only the two keys change; fields, order and
content fingerprints unchanged; `check_bib` clean), backs up cdl.bib and the results under
`.bibcheck/apply-2026-09-30b-answers/`, writes the logs, runs the production pipeline for the
batch, records the approvals, runs the negative controls, repeats the pipeline and exports
`verification/baseline.jsonl.gz` and `verification/review-queue.jsonl.gz`. Results:
[answers0930b-results.json](answers0930b-results.json); the second (resumed) run's log:
[attempt2.log](attempt2.log).

Batch: 21 entries (the swapped pair, the four parser-fix entries, the 7 approved entries and
every entry not accepted, 15 before).

| Stage | Requests | Review writes | Result |
|-|-|-|-|
| pipeline (resumed run) | 0 | 0 | nothing accepted lost; swapped pair `metadata_verified`, same accepted records |
| approvals | 0 | 1 | 7 `human_verified` (6 recorded in the first run, ScotEtal07 again) |
| negative controls | 0 | 0 | replaying the revoked approval refused for ScotEtal07, KahaMill13, Hook69 ("This exact approval was revoked ...") and Mink15 ("Entry changed since review"); each revocation still matches its old approval and not the new one |
| repeat | 0 | 0 | identical to the state after the approvals |

The first run's pipeline stage made 0 requests and 1 review write, then the approvals.

Swap check: KahaEtal08a (reply) `metadata_verified`, accepted Crossref 10.1037/a0013724,
fingerprint v2:ee40d1e4...; KahaEtal08b (chapter) `metadata_verified`, accepted research
evidence 10.1016/b978-012370509-9.00185-6, fingerprint v2:87db5ab9... Each is the same result
under the same content fingerprint as before the swap. The research evidence
(`research_route.load_evidence`) maps the wave-6 and batch-11 rows (first keyed KahaEtal08c) to
the new KahaEtal08a and the wave-8 and batch-19 rows (keyed KahaEtal08a) to the new KahaEtal08b.

Library after the batch (`bibcheck.py crossref status cdl.bib`): `6384 entries:
human_verified=23, metadata_verified=6353, needs_review=8`. The 8 are the surname-rule entries
of 2026-09-30 (BragEtal99, MeyeEtal88, NoldEtal98, RobeEtal99, SchaEtal11, StJaEtal08,
StJaEtal12, StJaScha13). A restore of the exported baseline into an empty database gives the
same status line and the same result for every entry ([restore_check.py](restore_check.py)).

## Other references to the swapped keys

- `verification/research-2026-09-25/postcheck.py`: `renamed_away` read key-renames.json as a
  last-row-wins map, which after the swap sent KahaEtal08c (the reply) to the chapter. It now
  composes the log in order; over the whole log only KahaEtal08c's redirect changes (checked
  2026-09-30). Test: `test_renamed_away_follows_the_log_in_order_through_a_key_swap`.
- Tests and fixtures (`tests/test_research_postcheck.py`, `tests/test_research_route.py`,
  `tests/fixtures/research_route/`, `tests/fixtures/cdl-prewave1-2026-09-26.bib`) name the keys
  as they were when frozen; they read no live file and pass unchanged, so they were not edited.
- `bibcheck/bibtex_checker.ipynb` (old cell outputs) and the earlier `verification/` records use
  the keys as they were at the time; they are history and were not edited.
