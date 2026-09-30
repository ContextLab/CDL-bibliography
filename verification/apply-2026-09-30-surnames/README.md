# Surname rule of 2026-09-30

The user's answer to [CONFIRM.md](../2026-09-29-user-review/CONFIRM.md) question 5 (2026-09-30):

> one source is sufficient; manual entry is the weakest part. notify user if mismatch is found and ask how they want to resolve it

It replaces Claude's rule that a surname change needs corroboration (decision log:
[resolution-plan README](../resolution-plan-2026-09-22/README.md), "Rules Claude adopted, then
confirmed or replaced by the user (2026-09-30)"). One authoritative source record that agrees
with a cited surname verifies it. When the cited surname and a source's disagree, the checker
neither keeps the cited spelling nor applies the source's: the entry stays `needs_review` with an
issue that names both spellings and the source, and the user decides. No surname in `cdl.bib`
was changed.

## Code paths changed

Every path that settled a surname mismatch without the user:

| Path | Before | Now |
|-|-|-|
| `auto_review.registry_surname_typo` (machinery 2026-09-25, rule 14) | a Crossref surname that the DOI-linked PubMed record and other cdl.bib entries contradicted was resolved in the citation's favour, and the entry verified | removed; `registry_surname_mismatch` leaves the author finding open and names each differing position, both spellings and both records; `reassess` puts that finding first in the entry's issues |
| `correction_proposals.surname_change_hold` (used by the single-source, corroborated and PubMed-only proposals, `pmc_corrections`, `catalogue_review`, `extra_sources`, and through `osf_review.classify` the OSF, DataCite, ACL and SfN routes) | a surname change went ahead with a second source, or when other cdl.bib entries used the new spelling; library consensus held it otherwise | every surname change is held, naming both spellings and the source; reorderings are not changes (`surname_changes`) |
| `correction_proposals` corroborated author proposal | Crossref + PubMed agreeing on a new surname was proposed | held |
| research post-check (`verification/research-2026-09-25/postcheck.py`) | a researcher's respelling was applied when two hosts, the DOI record, an author-deposited record (arXiv, Zenodo), cdl.bib's own spelling or the reviewer supported it | every respelling (the researcher's or the reviewer's) is held with flag `surname_mismatch`, the cited name kept |

`library_people` / `_person_key` (the library-consensus index) and the post-check's
`house_name_uses` / `deposited_witnesses` had no other use and were removed.
`auto_review.RESOLVER_VERSION` is unchanged: the rule only withdraws a resolution, so no
unresolved entry can gain from a revisit, and this batch rechecked every accepted entry itself.

## Tests

Changed to the new rule (each keeps its negative controls):
`tests/test_correction_proposals.py` (MeyeEtal88 held for the user; single-source, library-use
and second-source cases now held), `tests/test_phase0_rules.py` (RebeEtal02, CleeMcCl91 held;
RacsEtal08's Nagymáté), `tests/test_machinery_2026_09_25.py` (MeyeEtal88 named, not resolved),
`tests/test_sfn_abstracts.py` (KrauEtal12 held on the mismatch, page named),
`tests/test_research_postcheck.py` (the release rules no longer release: FreeEtal03b, RuggEtal96,
AguiEtal96, KatzEtal89, Brig12, VanEEtal01, ToluEtal12, TulvThom73, CaliVita05, ChanEtal20,
WhitEtal96; the wave-3 review resolution now leaves FreeEtal03b to the user).

Added: `test_meyer88_agreeing_single_source_is_accepted` (agree: Crossref alone verifies once
its byline agrees), `test_meyer88_crossref_mismatch_is_named_for_the_user` and
`test_meyer88_negative_controls` (disagree: `needs_review`, both spellings named; an order
change is not named), `test_surname_change_hold_controls` (agree: no hold for a given-name
change, an accent or a reordering; disagree: both spellings and the source named),
`test_format_fix_applies_beside_a_held_respelling`, `test_surname_mismatch_names_both_spellings_and_hosts`.

## Run

    python bibcheck.py crossref restore verification/baseline.jsonl.gz
    python verification/apply-2026-09-30-surnames/apply.py --apply
    python verification/apply-2026-09-30-surnames/build_surnames.py

[apply.py](apply.py) evaluates every saved result offline against the new rule (no write, no
request), runs the production pipeline for the affected entries plus every `needs_review`
entry, repeats it (zero requests, zero review writes), and exports the baseline and queue.
Results: [surnames0930-results.json](surnames0930-results.json).

Run on 2026-09-30 (EDT), on the database restored from the baseline of commit 856d637
(6,361 `metadata_verified`, 16 `human_verified`, 7 `needs_review`):

| Stage | Requests | Review writes | Result |
|-|-|-|-|
| library-wide offline evaluation (6,384 entries) | 0 | 0 | 8 status changes, all `metadata_verified` → `needs_review`, exactly the retired rule's approvals; 2 more entries (TervEtal00, TulaEtal07, verified on PMC full text) gain a named Crossref mismatch in a candidate; 2,612 other differences are recheck bookkeeping that the previous code produces too, not written |
| production pipeline, 17 entries (those 10 + the 7 already `needs_review`) | 1 | 21 | 15 `needs_review`, 2 `metadata_verified`; nothing newly accepted; no accepted result outside the batch changed |
| repeat | 0 | 0 | identical |

Entries moved to `needs_review` (their approval rested on the retired registry-surname-typo rule;
PubMed prints the cited spelling in each): MeyeEtal88 (Crossref "Kounois"), BragEtal99 (Crossref
"Buzs�ki"), RobeEtal99 (Crossref "Georges-Fran�ois"), NoldEtal98 (Crossref "DʼEsposito" with a
modifier apostrophe), SchaEtal11, StJaEtal08, StJaEtal12 and StJaScha13 (Crossref "St. Jacques").
Each now carries the issue "author: surname mismatch: author N is ... in the citation and PubMed
... but ... in Crossref ...".

Library after the batch: 6,384 entries, 6,353 `metadata_verified`, 16 `human_verified`, 15
`needs_review`. A restore of the exported baseline into an empty database gives the same status
line and the same result for every entry.

The surname scan of the whole library ([scan.py](scan.py), [build_surnames.py](build_surnames.py))
found 137 mismatches in 100 entries (20 spelling, 1 written-out umlaut, 85 name split
differently, 16 punctuation or spacing, 15 unreadable source characters), plus 7 entries whose
sources differ only in author order. They are listed, with a question each, in
[SURNAMES.md](../2026-09-30-user-review/SURNAMES.md) and
[surnames.json](../2026-09-30-user-review/surnames.json). In 130 of the 137 the differing
record is Crossref's, in entries verified on another record (research evidence, PubMed, full
text); those entries stay verified on the source that agrees with them until the user answers.

## Known checker defects found by the scan (not fixed here)

The scan had to work around two parsing gaps in the checker's own name handling. In the
entries found, each makes the checker's author comparison fail (so it can hold an entry back),
not pass:

- a tilde accent outside braces (`I L Pi\~{n}a`, PollEtal00; `A N\'{u}\~{n}ez`, NuneEtal87):
  BibTeX name splitting reads `~` as a space, so `splitname` returns the surname `{n}a`;
- `\aa` (`E Id{\aa}s`, MagnEtal98): `verification.normalized` rejects it as an unknown command.
