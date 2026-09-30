# Stage 2C (2026-09-25): research-pilot verdicts, PRs #87 and #88, replacement list

These batches apply the user's decisions recorded in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md): the research-pilot
verdicts (30 correct, 20 wrong with notes), keys that follow corrected metadata, preprints that cite their
latest version, DOIs everywhere, and the merge of PRs #87 and #88.

The runner is [`apply.py`](apply.py). It keeps the stage 2B discipline of `../apply-2026-09-25d/`:

1. Proposals are frozen with entry fingerprints (`<batch>-proposals.json`).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-25e/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0 review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore.
8. The full pytest suite and `verification/benchmark/run.py` (60/60) must pass, then the batch is committed.

The runner adds three things over the stage 2B-ii one (apply-2026-09-25d). Each is asserted in staging:

- entry-type changes;
- a user-approved replacement (`kind: replace`) and a user-approved removal (`kind: remove`);
- `verify_keys`, which are unchanged entries verified together with the batch (the merged PR entries).

`.bibcheck/validate-current-checkpoint.py` now reads [`library-changes.json`](library-changes.json). That
file lists the removed keys, the keys added by the merged PRs, and the last staged file. Every key rename
is logged in [`../key-renames.json`](../key-renames.json).

Library counts come from the batch runs and `bibcheck.py crossref status cdl.bib` (metadata_verified /
needs_review).

| Step | Entries | Status change in batch | Requests (run / repeat) | Review writes (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|-|
| start | | | | | 4,398 / 2,024 (6,422) | eefdacf |
| pilot001, attempt 1 | 49 | stopped: `KeyError: 'accepted_doi'` in the SfN route; cdl.bib restored | | | | |
| pilot001 | 47 proposals (46 keys after the removal) | +14 verified (15 of 46); 31 needs_review | 9 / 0 | 68 / 0 | 4,412 / 2,009 (6,421) | 689de07 |
| merge PR #87 | +30 new, YangEtal25 → YangEtal25a | not yet verified | | | | ebff8e4 |
| merge PR #88 | +30 new, FitzEtal26 → FitzEtal26b, 16 edited | not yet verified | | | | 4bc99ef |
| prfix001 | 35 fixes; 79 keys verified (78 PR keys + Aust14) | 69 verified, 10 needs_review | 123 / 0 | 215 / 0 | 4,470 / 2,011 (6,481) | 2179d34 |
| prfix002 | 2 (arXiv version pins) | +1 verified (WangEtal24); YangEtal25a stays verified | 4 / 0 | 6 / 0 | 4,471 / 2,010 (6,481) | the commit that adds this README |

## pilot001: research-pilot verdicts

Proposals are built by [`build_pilot.py`](build_pilot.py), with results in
[`pilot001-results.json`](pilot001-results.json).

The 31 entries the user marked **correct** are applied as proposed, with the house forms decided since the
pilot. DOIs are lowercase, GelmEtal13's edition is `3\textsuperscript{rd}`, and an emptied field is dropped
(Arch11a's `booktitle`). AndeEtal66 takes `number = {3--4}`, which the user corrected.

The 20 marked **wrong** follow `../research-pilot-2026-09-24/followup.json`:

- **DOIs:**
  - BiswEtal95, PuceEtal99, LiEtal19, ParaEtal04 and KahaMill13 get their DOIs. KahaMill13 also gets the
    title "Memory recall, dynamics".
  - vanEEtal18 gets the eLife DOI 10.7554/elife.36928.
  - ZimaEtal23: the PsyArXiv DOI moves from `volume` to `doi`.
  - HogeEtal99 already had its DOI (adddoi002), so it needs no change.
- **Proceedings:** MikoEtal13b becomes @inproceedings, and its NAACL booktitle has no year. XiaoEtal10's
  booktitle has no year.
- **Chapter:** ScotEtal07 becomes @incollection for the chapter, with editors Abell and Lederman, publisher
  Erlbaum, address Mahwah, and no pages.
- **Titles and volumes:**
  - Hook69: the title is "The posthumous works of {R}obert {H}ooke".
  - Jame90: volume `I`, APA DOI 10.1037/10538-000, and `W James`.
- **Mink07 → Mink15 (6th edition, user).**
  - The LoC record shows "Sixth edition", Wolters Kluwer, Philadelphia, 2015. Its contents list starts with
    "Functional organization of the basal ganglia" ([SRU query for LCCN 2015458479](https://lx2.loc.gov/sru/lcdb?version=1.1&operation=searchRetrieve&maximumRecords=1&recordSchema=mods&query=bath.lccn%3D2015458479)).
  - The [LWW product page](https://shop.lww.com/Parkinson-s-Disease-and-Movement-Disorders/p/9781608311767)
    reads: "1. Functional Organization of the Basal Ganglia Jonathan W. Mink … Edition 6 Publication Date May 21, 2015".
  - No pages were found, so none are given.
- **Beaz05 → Beaz96 (user-approved replacement).** The new entry is D M Beazley, "{SWIG}: an easy to use tool
  for integrating scripting languages with {C} and {C++}", Fourth Annual {USENIX} {Tcl/Tk} Workshop,
  Monterey, CA, 1996.
  - Sources: the [USENIX paper page](https://www.usenix.org/legacy/publications/library/proceedings/tcl96/beazley.html)
    and the [proceedings index](https://www.usenix.org/legacy/publications/library/proceedings/tcl96/)
    ("July 10-13, 1996 Monterey, California").
  - No DOI or pages were found.
  - It is logged in key-renames.json with `"kind": "replacement"`.
- **NetwLab25: REMOVED (user-approved removal, research-pilot verdict 2026-09-25).** This removal and the
  Beaz05 replacement are the only keys that disappear in pilot001.
- **Palm78:** kept unchanged. This was Claude's choice, not the user's. The user's page note was "again, add DOI" (verdict wrong, 2026-09-25 00:06 EDT), and "keep unchanged" was Claude's instruction to an agent (2026-09-25 11:10 EDT). The DOI question is open: see [../2026-09-29-user-review/REVIEW.md](../2026-09-29-user-review/REVIEW.md).
- **RamaEtal12b and SommEtal12: HELD, not applied.** The SfN route raises an exception when it verifies an
  entry (see "Code change needed" below).

Other changes in pilot001:

- **Key renames:**
  - KahaEtal22 → KahaEtal24: the year changes 2022 → 2024 (The Oxford Handbook of Human Memory).
  - Mink07 → Mink15.
- **`bibcheck/caps.txt`:** adds `TclTk` and `HallCRC`. The formatter lowercases the part of a slash word
  after the slash (`Hall/{crc}`). With `HallCRC`, GelmEtal13's publisher is `Chapman and {Hall/CRC}`. The
  one other entry with that publisher, Altm99, then had to change from `Chapman \& Hall/crc` to
  `Chapman \& {Hall/CRC}`. Altm99 is in the batch and stays verified.

**Statuses after pilot001 (46 batch keys): 15 metadata_verified, 31 needs_review.**

Newly verified (14): CalvEtal97, Curr04, HowaEtal08b, LegeEtal69, LiEtal19, McCrGrac07, NilsEtal75,
RovaVirs79, SchwHump73, Unde48a, Weiz66, XiaoEtal10, ZimaEtal23, ZrenEtal11. Altm99 stays verified.

The user reviewed all 31 unresolved entries in the pilot. The table gives the issue that remains
between each entry and its closest source record. Most of these are limits of the verification machinery.

| Closest-source issue | Entries |
|-|-|
| The editor or edition field has no deterministic verifier | GelmEtal13 (edition), KahaEtal24 (editor) |
| Author list differs from the source record: given names missing (AndeEtal66, LeVaEtal10; Crossref also misspells "Hamberoer"), author surnames/order (BiswEtal95: Crossref splits "Zerrin Yetkin"), or author count (ParaEtal04, PiefEtal03, PuceEtal99: the OUP Crossref records list only the first author) | AndeEtal66, LeVaEtal10, BiswEtal95, ParaEtal04, PiefEtal03, PuceEtal99 |
| A preprint relation on the published article ("related versions") | vanEEtal18 |
| The source lacks pages or issue, or has only an online-year conflict | BiddMarl87, Youn61, NastEtal20, PhelEtal18, Kais90, RosePaul90 |
| The catalogue edition is unresolved (LoC) | Bart32, Hook69, Hume07 |
| No source route; the closest record is a reissue or a different work | Beaz96, EichMaca06, Mink15, Pach74, ScotEtal07, SilbEtal01, Shan20, Gaut08, RaypWall67 |
| Other | Arch11a (title vs Europe PMC), MikoEtal13b (the ACL Anthology page has no address), Jame90 (the APA record's title and publisher are "The principles of psychology, Vol I." and "Henry Holt and Co"), KahaMill13 (the SAGE record has no authors, and its type is reference-entry) |

These entries can be signed off as human-verified with `crossref approve`, because the pilot page already
holds the user's review. That was not done here, since it needs the user's go-ahead.

**Attempt 1** stopped in the SfN route, in `osf_review.merge`, at
`result['accepted_doi']`: KeyError. cdl.bib was restored byte-for-byte. The attempt's backup, snapshot,
staging, report and log are in `.bibcheck/apply-2026-09-25e/pilot001-attempt1-sfn-keyerror/`. After the
restore, one result with the original fingerprint differed from the committed baseline: McCrGrac07 had a
newer `checked_at` and candidate list, but the same status (needs_review). McCrGrac07 was in the rerun
batch, so the rerun replaced it.

## PRs #87 and #88

Both PR branches were merged with `git merge --no-ff`.

- **#87** merged cleanly, with cdl.bib and caps.txt `IRE`.
- **#88** had two conflicts:
  - MannEtal11: the PR's initials byline was taken (house rule).
  - Both PRs appended entries at the end of the file; both blocks were kept.
- The duplicate `Doi` fields that the merge produced in OwenMann24 and HeusEtal21 were removed. Each held
  the same DOI twice.
- Renames from the PRs' collision rule are logged: YangEtal25 → YangEtal25a and FitzEtal26 → FitzEtal26b.

**prfix001** ([`build_prfix.py`](build_prfix.py), [`prfix001-results.json`](prfix001-results.json)) fixes every
entry the PR check found ENTRY-WRONG and applies the house rules. The evidence quotes are in the proposals.

- **Pages:**
  - KothEtal25: `IMAG.a.136` (Crossref article-number) and a lowercase DOI.
  - KonkEtal21 `1417--1427.e6`, ChenEtal21 `4293--4304.e5`, SchwEtal22 `4808--4816.e4`.
- **Entry types:** BauEtal17 and DalaTrig05 become @inproceedings, with their CVPR DOIs.
- **Other single fields:**
  - BindEtal16: number `3--4`.
  - Sips13: edition `3\textsuperscript{rd}` (LoC LCCN 2012938665).
  - SchaAbel77: the Oxford comma (LoC LCCN 76051963).
  - YangEtal25a: volume `2510.00183`.
  - YangEtal25b: the full 60-name arXiv byline.
- **Renames:**
  - WangEtal22 → **WangEtal24**: the latest arXiv version, v2, is dated 2024-02-22.
  - Mann26 → **MannClau26**: DataCite lists two creators, and the entry now reads `J R Manning and {Claude}`.
- **DOIs:**
  - #87: 13 articles and proceedings papers get their DOIs, the arXiv entries get arXiv DOIs, and
    Chom56, ChomMill58, Chom59 and ReimGure19 get lowercase DOIs.
  - #88: Beli92 (the single-slash APA form), KrakEtal02, Niel17 and StroEtal25 get DOIs, and VallWalk21's
    DOI is lowercased.
  - The PR books verified from LoC (Chom65, ChomHall68, OsgoEtal57, SchaAbel77, Sips13) and Hass16 have no
    DOI, the same as the 89 LoC books in adddoi002.
- **Aust14:** publisher `T Eagerton` → `T Egerton`. The LoC MARC 264 field in the saved catalogue evidence
  reads "Printed for T. Egerton, Military Library, Whitehall, 1814", and field 700 reads "Egerton, Thomas
  (Bookseller)". The author becomes `J Austen` (initials rule).

**prfix002** ([`build_prfix002.py`](build_prfix002.py)) pins the latest arXiv version, following the user
rule "pin the version where the server supports it": WangEtal24 gets `2212.03533v2` and YangEtal25a gets
`2510.00183v2`. Unpinned, the arXiv route compares the year with DataCite's publicationYear (2022) and holds
WangEtal24.

### Per-PR verification (production `verify --auto-review` pipeline, including the 2026-09-25 routes)

| PR | Entries | Verified | Unresolved |
|-|-|-|-|
| #87 add-feature-representation-refs | 31 | 28 | 3 |
| #88 nightwarden-refs | 47 (31 new, 16 edited) | 42 | 5 |

WangEtal24 was held after prfix001 (year vs DataCite's first-version year) and verified after prfix002.

The unresolved entries and why:

| Entry | Label | Reason |
|-|-|-|
| DalaTrig05 (#87) | machinery/source | The Crossref record has no date parts, and its booktitle carries the year and `(CVPR'05)` |
| Klee56 (#87) | machinery | The editor and address fields have no deterministic verifier. The De Gruyter container is "Automata Studies. (AM-34)" |
| Hass16 (#87) | machinery gap | A TED-talk web page; there is no web-page route |
| FeliEtal98 (#88) | machinery/source | The Crossref title is truncated, and its author suffix field holds degrees. The PubMed title matches the entry |
| LantEtal26 (#88) | machinery | Print year 2026 against issued 2025; the full-text dates do not support the print year |
| Mann23 (#88) | machinery | The container subtitle is not joined, and the publisher is "Springer International Publishing" |
| Mann24 (#88) | machinery | The editor field has no deterministic verifier |
| HeusMann18 (#88) | needs the user | A CCN 2018 abstract. The source gives fewer initials and no pages, and its booktitle includes the year |

Aust14 stays needs_review. The catalogue reports "Transcribed responsibility differs from the complete named author
list": the 1814 edition was published anonymously, 'by the author of "Sense and sensibility" and "Pride and
prejudice."' (LoC 245 $c). The publisher is now correct.

**PR machinery defects from `../pr-check-2026-09-25/README.md` that no longer apply:**

- #9: `3\textsuperscript{rd}` is accepted, and Sips13 verifies.
- #10: `IMAG.a.136` passes the formatter, and KothEtal25 verifies.
- #2: PigeEtal12 verifies.
- #1: Schr03 verifies.
- #3: ChenEtal21 and SchwEtal22 verify with their `.eN` pages.
- #7: Chom56 verifies.
- #6: Chom65 verifies.
- #14: Spee22, ReimGure19, FitzEtal26a and MannClau26 now verify through the DataCite, ACL and OSF routes.

## replacements-list: preprint → published (FOR USER APPROVAL, NOT APPLIED)

[`build_replacements.py`](build_replacements.py) writes [`replacement-candidates.json`](replacement-candidates.json).
It scans all 85 cited preprints (bioRxiv, PsyArXiv, arXiv, SSRN and others) and flags a preprint in two
cases:

- The Crossref record of the cited preprint has `relation.is-preprint-of`. This covers the OSF route's three
  `replacement` entries and adddoi002's three skipped bioRxiv entries.
- The arXiv API gives an `arxiv:doi` for it. One request covered all 43 cited arXiv ids.

For each flagged preprint, the published version's Crossref record gives the draft entry and the key.

| Current entry | Published version (DOI) | Venue, year | Authors | Proposed key | Notes |
|-|-|-|-|-|-|
| BetzEtal19 (bioRxiv) | 10.1016/j.neuroimage.2020.116687 | NeuroImage 213:116687, 2020 | R F Betzel, L Byrge, F Z Esfahlani, D P Kennedy | BetzEtal20 | |
| ChieHone19 (bioRxiv) | 10.1016/j.neuron.2020.02.013 | Neuron 106(4):675--686.e11, 2020 | H-Y S Chien, C J Honey | ChieHone20 | |
| GralFinn21 (PsyArXiv) | 10.1093/scan/nsac019 | Soc Cogn Affect Neurosci 17(6):598--608, 2022 | C Grall, E S Finn | GralFinn22 | |
| LeeEtal19 (bioRxiv) | 10.1016/j.cell.2020.09.024 | Cell 183(3):620--635.e22, 2020 | J S Lee, J J Briguglio, J D Cohen, S Romani, A K Lee | LeeEtal20b | 5 authors, not 4. The existing LeeEtal20 (Lee, Bellana & Chen) becomes LeeEtal20a |
| LuriEtal18 (PsyArXiv) | 10.1162/netn_a_00116 | Network Neuroscience 4(1):30--69, 2020 | D J Lurie ... V D Calhoun (23) | LuriEtal20 | Keep "Keilholz": Crossref's "Kheilholz" is a single-source surname change |
| NussEtal18 (PsyArXiv) | 10.1037/xge0000753 | J Exp Psychol Gen 149(10):1919--1934, 2020 | K Nussenbaum, E Prentis, C A Hartley | NussEtal20 | |
| SilvEtal19 (bioRxiv) | 10.1523/jneurosci.0360-19.2019 | J Neurosci 39(43):8538--8548, 2019 | M Silva, C Baldassano, L Fuentemilla | SilvEtal19 (unchanged) | Same key: same first author, author count and year |
| ZhenEtal19 (arXiv 1904.11793) | 10.1073/pnas.1922248117 | PNAS 117(33):20244--20253, 2020 | M Zheng, A Allard, P Hagmann, Y Alemán-Gómez, M Á Serrano | ZhenEtal20 | 5 authors, not 4 |

Each draft holds the source's own values. On approval it is put into house form (sentence-case title,
LaTeX accents, house journal name) and has to verify before the preprint entry is removed. Each
replacement is then logged in key-renames.json.

The scan has a known limit: arXiv preprints later published in conference proceedings rarely carry
`arxiv:doi`, so those are not detected.

## Code change needed (files this stage does not own)

1. **`bibcheck/osf_review.py` `merge()`** reads `result['accepted_doi']` whenever a route verifies an entry.
   An SfN approval has no DOI, so `run_sfn_review` raises `KeyError: 'accepted_doi'` the first time it
   verifies an entry. RamaEtal12b and SommEtal12 hit this. The routes measurement never verified an SfN
   entry, so the path had not run before.
   - Suggested fix: `result.get('accepted_doi')`. `preprint_review.context_issues` works with `None`.
   - Add a `run_sfn_review` test on a verifying fixture.
   - Once fixed, RamaEtal12b (swap Baltuch before Kahana; program 800.09) and SommEtal12 (@inproceedings,
     SfN Abstracts, 746.04, New Orleans) can run as a small batch; their proposals are in followup.json.
2. **Formatter:** `helpers.format_journal_name` lowercases the part of a slash word after the slash
   (`Hall/{CRC}` becomes `Hall/{crc}`, and `{Tcl/Tk}` becomes `{tcl/tk}`). The caps.txt entries `HallCRC` and
   `TclTk` work around it here.
3. **arXiv route:** an unpinned arXiv id is compared with DataCite's first-version publicationYear. The
   user's latest-version rule therefore needs the id pinned (`<id>vN`), as prfix002 does.
   `build_adddoi`-style scans could propose pins for other multi-version arXiv entries.

## Final library counts

`bibcheck.py crossref status cdl.bib`: **6481 entries: metadata_verified=4471, needs_review=2010**.
At the start there were 6,422 entries (4,398 / 2,024). Since then, 60 PR entries were added, 1 entry was
removed, and 7 keys were renamed (key-renames.json): KahaEtal24, Mink15, Beaz96 (replacement),
YangEtal25a, FitzEtal26b, WangEtal24 and MannClau26.

## Checks after each committed batch

After pilot001, prfix001 and prfix002:

- `.bibcheck/validate-current-checkpoint.py` gave an exact restore: 6,421 entries after pilot001 and 6,481
  after prfix001 and prfix002, with 0 repeat imports and SQLite ok.
- Full pytest passed (1,537).
- `verification/benchmark/run.py` passed 60/60, with 0 false acceptances.
- `bibcheck.py verify --no-citations` printed "looks good!".
