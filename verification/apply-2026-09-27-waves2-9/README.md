# Stage 3 (2026-09-27): research waves 2-9

This folder applies the post-checked research of waves 2 to 9
(`../research-2026-09-25/wave{2..9}/merged.json`, which already carries the user's cross-wave decisions and
the resolution batches in `../resolution-2026-09-26/`), one batch and one commit per wave:

- every **ready** row (`needs_user` false, no `remove_entry`) gets its final changes: the `final_changes`
  values, the field `removals`, the entry type and the key plan (`rename`, or `collision` with the existing
  entry's `also_rename`);
- every row with `remove_entry` is deleted, unless the post-check marked the drop a no-op (the entry is already
  absent, or its key is a reused key listed in `../key-deletions.json`). KahaEtal08b and JacoEtal05b are never
  deleted: they now name other works;
- every row with `needs_user` true is left exactly as in HEAD. Those entries are held for the user (their
  evidence is being strengthened) and will be applied later.

The merged files were frozen at the start (2026-09-26 22:29 ET) under
`.bibcheck/apply-2026-09-27-waves2-9/inputs/`, and each proposals file records the sha256 of its input. The frozen
files are the ones committed in f8e9e5d ("Post-check waves 2-9 with resolution decisions"); later post-check and
resolution commits (9f44dd0, 71b157b, f1bd122 and on) are not in these batches.

## Why one commit per wave

The pipeline cost grows with the number of batch keys, not with the number of batches. The wave-1 batch (158
kept keys) took 1,134 s and its zero-request repeat 782 s, so one batch of all eight waves would cost about
as much as eight batches. Per-wave batches keep each commit reviewable and let a failure stop at one wave. The
waves are applied in order: each wave's proposals are built against cdl.bib after the waves before it, and a
row's key is followed through the earlier batches' renames.

## Discipline

The runner is [`apply.py`](apply.py). It reuses `../apply-2026-09-26-wave1/apply.py` (the stage that allows a
new key to be a key the same batch removes) on `../apply-2026-09-25f/apply.py` and `../apply-2026-09-25e/apply.py`,
pointed at this folder:

1. The proposals are frozen with entry fingerprints (`<wave>-proposals.json`, built by [`build.py`](build.py)).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-27-waves2-9/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0 review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. [`log.py`](log.py) logs the renames in `../key-renames.json` and the removals in `../key-deletions.json`
   (reason and decision source: the resolution batch and its notes, from `merged.json`), and writes
   [`library-changes.json`](library-changes.json).
8. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore
   (`../completion-2026-09-15/restore-latest.json`). It now reads this folder's `library-changes.json`. The
   renames of these batches chain (wave 1: Frie08 -> Frie08a and Frie06 -> Frie08b; wave 8: Frie08a -> Frie12 and
   Frie08b -> Frie08), so one flat old -> new map no longer describes the library. The validator applies the
   earlier flat map and then this folder's batches as ordered `steps` (removals, then simultaneous renames). The
   previous validator is kept as `.bibcheck/apply-2026-09-27-waves2-9/validate-current-checkpoint.py.bak`.
9. The committed state is proven first: a scratch worktree at HEAD gets the batch's files and a commit, and the
   full pytest suite and `verification/benchmark/run.py` must pass there. Only then is the batch committed here.
   The worktree has no `.bibcheck/`: the suite's gate tests take the Crossref contact from `CROSSREF_MAILTO`
   (read from the main cache), and the network caches the suite reads (`research-postcheck`, `research-pilot`,
   `pdf-benchmark`) are linked in. Without them two tests fetch live records and fail.

## Five pending entries verified with wave 2

Commits e920c54 and ce6c315 (after the wave-1 run) edited Galt83, BancEtal65, Yate66, Wech45 and Mann06 without
running the pipeline, so they were `pending` at the start and the fresh restore could not import them (6,395 of
6,400). They are the wave-2 batch's `verify_keys` (unchanged entries the pipeline verifies with the batch; added to
`wave2-proposals.json` after a first wave-2 run, which was then redone from the backup).

## Exceptions that `check_bib` forces (in build.py)

- `HOUSE_FORM`: the formatter's fixed point for an approved value, when it only changes the form: braced
  `{American}`, `{University}`, `{MIT}`, `{Georg}`; lowercased braced acronyms such as `({eurospeech})`,
  `({mobisys})`, `{ieee/acm}` (the wave-1 precedent, Kipp01); `{A}` after a colon in a booktitle; a braced capital
  after opening quotes (`` ``{G}eneral ``); `(1993{a})`; `$1/{f}^2$`; `Chat{GPT}` and `{B}{ASIC}` for titles
  whose full braces the formatter strips; the software title `{naturalistic-data-analysis}/...`; and names
  with a dot accent or a Polish L in Unicode (the formatter strips `\.` and garbles `{\L}`; cdl.bib already
  prints names in Unicode). Where the fixed point is the value as cited (Laks01's booktitle, RCor12's author,
  SzpuTulv11's booktitle), the change is not made.
- `HELD`: approved values that `check_bib` cannot accept in any form tried. They stay as cited:
  - pages it cannot parse: HeniEtal19 `ENEURO.0306-19.2019`, BrinCrag72 `28P--29P`, ViveEtal10 `24ra22`,
    and the roman-to-arabic ranges of Perr14, Unde45, Ward37, Webb17 and Calk96 (`i--97` and the like);
  - HeniEtal19's journal (`eNeuro` becomes `Eneuro`), Fish22's journal (`of a Mathematical` becomes
    `of {A} Mathematical`), RangEtal14's publisher (`PMLR` becomes `Pmlr`), BartEtal04c's address (`La Jolla`
    becomes `{LA} Jolla`);
  - Youn12's `url` (not a house field; its volume, number and pages are still removed);
  - KingEtal11's author list (`{RNS System in Epilepsy Study Group}` becomes `{ R N S System ...}`, as with the
    wave-1 FoodAdmi20a case), and with it the rename to MorrRNSS11 that follows the new author. Its title fix is
    applied.
- `DEFERRED_RENAMES`: Shim95 -> Shim95a is applied in wave 8 with Shim94 -> Shim95b (one cross-wave decision; a
  lone Shim95a fails the suffix rule in wave 2).
- `SUFFIX_RENAMES`: the suffix rule after a wave's renames: ChanEtal12b -> ChanEtal12, MairEtal09a -> MairEtal09
  (wave 2), LegaEtal11a -> LegaEtal11 (wave 3), CoheEtal08b -> CoheEtal08 (wave 4), Arch11a -> Arch11 (wave 6),
  Frie08b -> Frie08 (wave 8, as the wave-1 README expected) and deCa05b -> deCa05 (wave 9).

## Stopped before wave 5: a test reads the live cdl.bib (resolved in 084e453)

A dry run of all eight waves in a scratch worktree (every wave staged and `check_bib` clean) found that the
full suite breaks at wave 5: `tests/test_sfn_abstracts.py::test_held_on_surname_consensus` expects KrauEtal12's
proposed `R J Robinson` to be held by "library consensus", and `correction_proposals.library_people` reads the
live cdl.bib (`LIBRARY_BIB`). The consensus is KrauEtal13's cited `R J {Robinson I I }`, which wave 5 corrects to
`R J Robinson` (reviewer value, ready row). With wave 5 applied the test gets `proposal` instead of `held`. The
test is not ours to edit, so waves 5-9 are not applied here; their proposals were built and staged cleanly in the
dry run (build.py already holds their `check_bib` exceptions). No other test failed on the dry run's final
cdl.bib.

The test now reads the frozen pre-wave-1 bibliography (`tests/fixtures/cdl-prewave1-2026-09-26.bib`, 084e453),
so waves 5-9 went ahead from the re-run post-check below.

## Waves 5-9 and the wave 2-4 leftovers, from the re-run post-check (2026-09-27)

After the wave 2-4 commits the post-check was re-run against that cdl.bib with the final evidence rules (93ae192).
Its `merged.json` files were frozen on 2026-09-27 under `.bibcheck/apply-2026-09-27-waves2-9/inputs-93ae192/` (the
proposals record each sha256). They address every row by its current key, so `build.py` follows only the renames of
the batches built from them. The batches are applied in this order, one commit each:

- `wave2to4`: the rows of waves 2-4 that still carry changes (the 15 rows held in waves 2-4, now ready; the
  `check_bib` exceptions of those waves come back as rows and are held or kept in house form again).
- `wave5` ... `wave9`: every ready row and every drop that is not a no-op.

### The four needs_user rows

- ChanEtal12b (wave 2), MairEtal09a (wave 6), LegaEtal11a (wave 7) are flagged `not_in_bib` and "duplicate of"
  ChanEtal12 / MairEtal09 / LegaEtal11 only because the house suffix rule renamed them in the wave-2 and wave-3
  batches (`verification/key-renames.json`: ChanEtal12b -> ChanEtal12 and MairEtal09a -> MairEtal09 in wave2,
  LegaEtal11a -> LegaEtal11 in wave3). Their approved values are compared with the renamed entry and the difference
  is applied there (`NEEDS_USER` in build.py): ChanEtal12 needs nothing (its DOI came with wave 2); MairEtal09 gets
  the type, author, booktitle and DOI and loses the journal (the removal of the pre-post-check row, which saw the
  entry); LegaEtal11 gets its DOI.
- McCaEtal06 (wave 7) keeps `doi = 10.1609/aimag.v27i4.1904` by the user-rule default in
  `../resolution-plan-2026-09-22/README.md` ("A DOI that doi.org registers and the publisher's own article page
  prints (citation_doi), but that Crossref's API lacks ...: keep it"). Checked live on 2026-09-27: the handle API
  answers `"responseCode":1,"handle":"10.1609/aimag.v27i4.1904"`, doi.org redirects (HTTP 302) to the AAAI OJS
  article, whose page prints `<meta name="citation_doi" content="10.1609/aimag.v27i4.1904"/>`, and
  `api.crossref.org/works/10.1609/aimag.v27i4.1904` returns HTTP 404. Its other change (pages `12--14`) is already
  in the entry.

### New exceptions in these batches

- TsitEtal19 (wave 7): a reviewer's request "needs_user = True" appears as a change row; it names no bibliography
  field and is not written (`PSEUDO_FIELDS`). The row's resolution (batch-17, the preprint rule) already replaces
  the preprint with the Current Biology article, and the row is not needs_user.
- KahaEtal08a (wave 8): the key plan's rename to KahaEtal08 is not applied (`DEFERRED_RENAMES`). The user's
  decision reads "drop the \"a\" at the end of the key if this is the only KahaEtal08", and KahaEtal08b (the wave-1
  suffix rename of KahaEtal08c, a different work) is still in cdl.bib, so check_bib's suffix rule rejects it.
- LiEtal24a -> LiEtal24 (wave 7, suffix rule once LiEtal24b becomes LiEtal25).
- New house forms: MuelEtal16's title `{word}\_cloud` (the formatter capitalises the fully braced
  `{word\_cloud}`), HallGree08's booktitle `... Education: {A} Reference Handbook`, Murd89's booktitle
  `... Processes: the Tulane Flowerree Symposium on Cognition` (as RoedChal89), Herb91's booktitle
  `S{\"{a}}mtliche Werke` (the formatter lowercases `{W}erke`).
- New held field: MullSchu94's two-part pages.

### Fields check_bib rejects (they stay as in HEAD)

Every approved field that `helpers.check_bib` rejects in every form tried (`HELD` in build.py), across waves 2-9:

| Batch (wave) | Key | Field | Proposed value | Stays as | Why check_bib rejects it |
|-|-|-|-|-|-|
| wave2to4 (wave3) | HeniEtal19 | pages | `ENEURO.0306-19.2019` | (no such field) | check_bib's page check reads the eNeuro article number 'ENEURO.0306-19.2019' as an ambiguous page range and raises; the entry keeps no pages (as cited) |
| wave2to4 (wave3) | HeniEtal19 | journal | `eNeuro` | `Eneuro` | the journal formatter turns 'eNeuro' into 'Eneuro' ('{eNeuro}' into '{eneuro}'); the entry keeps 'Eneuro' (as cited) |
| wave5 (wave5) | KingEtal11 | author | `M J Morrell and {RNS System in Epilepsy Study Group}` | `D King-Stephens and A D Massey and C N Heck and D R Nair and G L Barkley and A J Cole and R P Gwinn and B C Jobst and Salanova and C T Skidmore and M C Smith and P C {Van Ness} and G K Bergey and M Duchowny and E B Geller and Y D Park and P A Rutecki and D C Spencer and R Zimmerman and J C Edwards and E Mizrahi and M J Berg and A Fessler and N B Fountain and J W Leiphart and R E Wharen and L J Hirsch and W Marsh and R E Gross and R B Duckrow and S Eisenschenk and C A O'Donovan and D A Bloch and T Crabtree and D Loring and A Plenys-Loftman and F T Sun and M J Morrell` | the author formatter turns the group author '{RNS System in Epilepsy Study Group}' into '{ R N S System in Epilepsy Study Group}' in every form tried (the wave-1 FoodAdmi20a case); the author list and the key (MorrRNSS11 follows the new author) stay as cited, the title fix is applied |
| wave2to4 (wave4) | BrinCrag72 | pages | `28P--29P` | `28` | check_bib's page check cannot read the suffixed pages '28P--29P' (PubMed 'PG  - 28P-29P') and raises; the entry keeps '28' |
| wave6 (wave6) | Fish22 | journal | `Philosophical Transactions of the Royal Society of London Series {A}: Containing Papers of a Mathematical or Physical Character` | `Philosophical Transactions of the Royal Society {A}` | the journal formatter capitalises the article in 'Containing Papers of a Mathematical or Physical Character' ('{A} Mathematical') in every form tried; the entry keeps 'Philosophical Transactions of the Royal Society {A}' |
| wave6 (wave6) | Perr14 | pages | `i--97` | `1--97` | check_bib's page check cannot read the roman-to-arabic range 'i--97' and raises; the entry keeps its current pages |
| wave6 (wave6) | Unde45 | pages | `i--33` | `i` | check_bib's page check cannot read the roman-to-arabic range 'i--33' and raises; the entry keeps its current pages |
| wave6 (wave6) | Ward37 | pages | `i--64` | `64` | check_bib's page check cannot read the roman-to-arabic range 'i--64' and raises; the entry keeps its current pages |
| wave6 (wave6) | Webb17 | pages | `i--90` | `1--90` | check_bib's page check cannot read the roman-to-arabic range 'i--90' and raises; the entry keeps its current pages |
| wave6 (wave6) | Calk96 | pages | `i--56` | (no such field) | check_bib's page check cannot read the roman-to-arabic range 'i--56' and raises; the entry keeps its current pages |
| wave7 (wave7) | Youn12 | url | `https://www.chronicle.com/article/inside-the-coursera-contract-how-an-upstart-company-might-profit-from-free-courses/` | (no such field) | url is not a house field (bibcheck/keep_fields.txt; check_bib: 'non-essential fields'); the removals of volume, number and pages are applied |
| wave9 (wave9) | RangEtal14 | publisher | `PMLR` | (no such field) | the publisher formatter turns 'PMLR' into 'Pmlr' ('{PMLR}' into '{pmlr}'); the entry keeps no publisher |
| wave9 (wave9) | BartEtal04c | address | `La Jolla, {CA}` | (no such field) | the address formatter reads 'La' as the Louisiana code ('{LA} Jolla, {CA}') in every form tried; the entry keeps no address |
| wave7 (wave7) | ViveEtal10 | pages | `24ra22` | `1--9` | check_bib's page check cannot read the article number '24ra22' and raises; the entry keeps '1--9' |
| wave7 (wave7) | MullSchu94 | pages | `81--190, 257--339` | `257--339` | check_bib's page check cannot read the two-part range '81--190, 257--339' (the user-rule default for an article printed in two parts) in any separator tried (', ', ',', '; ', ' and '); the entry keeps '257--339' |

Approved values applied in the form check_bib accepts (`HOUSE_FORM`); where that form is the value as cited, nothing changes:

| Wave | Key | Field | Proposed value | Applied value |
|-|-|-|-|-|
| wave2 | McGe36 | journal | `American Journal of Psychology` | `{American} Journal of Psychology` (the value as cited: no change) |
| wave2 | Spea04 | journal | `American Journal of Psychology` | `{American} Journal of Psychology` (the value as cited: no change) |
| wave2 | Spea04 | title | ````General intelligence,'' objectively determined and measured`` | ````{G}eneral intelligence,'' objectively determined and measured`` (the value as cited: no change) |
| wave3 | Hara96 | booktitle | `Computer Networking and Scholarly Communication in the Twenty-First-Century University` | `Computer Networking and Scholarly Communication in the Twenty-First-Century {University}` (the value as cited: no change) |
| wave3 | Hara96 | publisher | `State University of New York Press` | `State {University} of New York Press` (the value as cited: no change) |
| wave3 | BotvPlau03 | publisher | `New Bulgarian University` | `New Bulgarian {University}` (the value as cited: no change) |
| wave5 | VirtEtal20 | author | `P Virtanen and R Gommers and T E Oliphant and M Haberland and T Reddy and D Cournapeau and E Burovski and P Peterson and W Weckesser and J Bright and S J {van der Walt} and M Brett and J Wilson and K J Millman and N Mayorov and A R J Nelson and E Jones and R Kern and E Larson and C J Carey and {\.I} Polat and Y Feng and E W Moore and J {VanderPlas} and D Laxalde and J Perktold and R Cimrman and I Henriksen and E A Quintero and C R Harris and A M Archibald and A H Ribeiro and F Pedregosa and P {van Mulbregt} and {SciPy 1.0 Contributors}` | `P Virtanen and R Gommers and T E Oliphant and M Haberland and T Reddy and D Cournapeau and E Burovski and P Peterson and W Weckesser and J Bright and S J {van der Walt} and M Brett and J Wilson and K J Millman and N Mayorov and A R J Nelson and E Jones and R Kern and E Larson and C J Carey and İ Polat and Y Feng and E W Moore and J {VanderPlas} and D Laxalde and J Perktold and R Cimrman and I Henriksen and E A Quintero and C R Harris and A M Archibald and A H Ribeiro and F Pedregosa and P {van Mulbregt} and {SciPy 1 0 Contributors}` |
| wave5 | FallEtal20 | author | `J Fallon and P G D Ward and L Parkes and S Oldham and A Arnatkevi\v{c}i\={u}t\.{e} and A Fornito and B D Fulcher` | `J Fallon and P G D Ward and L Parkes and S Oldham and A Arnatkevičiūtė and A Fornito and B D Fulcher` |
| wave6 | ClanEtal19 | booktitle | `Proceedings of the Second Workshop on Fact Extraction and VERification ({FEVER})` | `Proceedings of the Second Workshop on Fact Extraction and Verification ({fever})` |
| wave6 | JoneEtal03 | booktitle | `8\textsuperscript{th} European Conference on Speech Communication and Technology ({Eurospeech})` | `8\textsuperscript{th} {European} Conference on Speech Communication and Technology ({eurospeech})` |
| wave6 | GeisEtal08 | booktitle | `Proceedings of the 10\textsuperscript{th} Workshop on Algorithm Engineering and Experiments ({ALENEX})` | `Proceedings of the 10\textsuperscript{th} Workshop on Algorithm Engineering and Experiments ({alenex})` |
| wave6 | BorzEtal23a | booktitle | `Proceedings of the 61\textsuperscript{st} Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations)` | `Proceedings of the 61\textsuperscript{st} Annual Meeting of the Association for Computational Linguistics (volume 3: System Demonstrations)` |
| wave6 | Ande04 | booktitle | `5\textsuperscript{th} {IEEE/ACM} International Workshop on Grid Computing` | `5\textsuperscript{th} {ieee/acm} International Workshop on Grid Computing` |
| wave7 | PimeEtal19 | booktitle | `{IEEE/ACM} International Conference on Mining Software Repositories` | `{ieee/acm} International Conference on Mining Software Repositories` |
| wave7 | AlvaEtal05 | publisher | `MIT Press` | `{MIT} Press` |
| wave7 | Amer23b | publisher | (unchanged by the research: `American Academy of Sleep Medicine`, exposed when Force is removed or the type changes) | `{American} Academy of Sleep Medicine` |
| wave7 | ChanEtal20 | title | `{naturalistic-data-analysis/naturalistic\_data\_analysis}` | `{naturalistic-data-analysis}/naturalistic\_data\_analysis` |
| wave7 | MuelEtal18 | title | `{word\_cloud}` | `{word}\_cloud` |
| wave8 | Mann23 | booktitle | (unchanged by the research: `Intracranial {EEG}: a guide for cognitive neuroscientists`, exposed when Force is removed or the type changes) | `Intracranial {EEG}: {A} Guide for Cognitive Neuroscientists` |
| wave8 | ChatGPT | title | (unchanged by the research: `{ChatGPT}`, exposed when Force is removed or the type changes) | `Chat{GPT}` |
| wave8 | Kurt81 | title | (unchanged by the research: `{BASIC}`, exposed when Force is removed or the type changes) | `{B}{ASIC}` |
| wave8 | Chai03 | booktitle | `{Vygotsky's} Educational Theory in Cultural Context` | `Vygotsky's Educational Theory in Cultural Context` |
| wave8 | RoedChal89 | booktitle | `Current Issues in Cognitive Processes: the {Tulane} {Flowerree} Symposium on Cognition` | `Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition` |
| wave8 | BjorRich89 | booktitle | `Current Issues in Cognitive Processes: The {Tulane} {Flowerree} Symposium on Cognition` | `Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition` |
| wave8 | SzpuTulv11 | booktitle | `Predictions in the Brain: Using Our Past to Generate a Future` | `Predictions in the Brain: Using Our Past to Generate {A} Future` (the value as cited: no change) |
| wave8 | BrowMcCo06 | booktitle | `Handbook of Binding and Memory: Perspectives from Cognitive Neuroscience` | `Handbook of Binding and Memory: Perspectives From Cognitive Neuroscience` |
| wave8 | HallGree08 | booktitle | `21\textsuperscript{st} Century Education: A Reference Handbook` | `21\textsuperscript{st} Century Education: {A} Reference Handbook` |
| wave8 | Murd89 | booktitle | `Current Issues in Cognitive Processes: The {Tulane} {Flowerree} Symposium on Cognition` | `Current Issues in Cognitive Processes: the Tulane Flowerree Symposium on Cognition` |
| wave8 | Herb34 | booktitle | `S{\"{a}}mtliche {W}erke` | `S{\"{a}}mtliche Werke` |
| wave8 | TalaTour88 | publisher | `Georg Thieme` | `{Georg} Thieme` |
| wave8 | Wern84 | publisher | `Georg Thieme` | `{Georg} Thieme` |
| wave9 | Laks01 | booktitle | `Biomedical Sciences and Human Experimentation at Kaiser Wilhelm Institutes: The Auschwitz Connection` | `Biomedical Sciences and Human Experimentation At Kaiser Wilhelm Institutes: the Auschwitz Connection` (the value as cited: no change) |
| wave9 | RCor12 | author | `{R Core Team}` | `{ R Core Team}` (the value as cited: no change) |
| wave9 | TardEtal08 | booktitle | `{IEEE/RSJ} International Conference on Intelligent Robots and Systems` | `{ieee/rsj} International Conference on Intelligent Robots and Systems` |
| wave9 | Yama08 | booktitle | `Dynamic Brain -- from Neural Spikes to Behaviors` | `Dynamic Brain -- From Neural Spikes to Behaviors` |
| wave9 | LiEtal16 | booktitle | `Proceedings of the 14\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services ({MobiSys})` | `Proceedings of the 14\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services ({mobisys})` |
| wave9 | TianEtal16b | booktitle | `Proceedings of the 17\textsuperscript{th} International Workshop on Mobile Computing Systems and Applications ({HotMobile})` | `Proceedings of the 17\textsuperscript{th} International Workshop on Mobile Computing Systems and Applications ({hotmobile})` |
| wave9 | LiEtal17b | booktitle | `Proceedings of the 15\textsuperscript{th} {ACM} Conference on Embedded Network Sensor Systems ({SenSys})` | `Proceedings of the 15\textsuperscript{th} {ACM} Conference on Embedded Network Sensor Systems ({sensys})` |
| wave9 | TianEtal18 | booktitle | `Proceedings of the 16\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services ({MobiSys})` | `Proceedings of the 16\textsuperscript{th} Annual International Conference on Mobile Systems, Applications, and Services ({mobisys})` |
| wave9 | TianEtal20b | booktitle | `Proceedings of the 21\textsuperscript{st} International Workshop on Mobile Computing Systems and Applications ({HotMobile})` | `Proceedings of the 21\textsuperscript{st} International Workshop on Mobile Computing Systems and Applications ({hotmobile})` |
| wave9 | LiEtal20 | booktitle | `Proceedings of the 18\textsuperscript{th} Conference on Embedded Networked Sensor Systems ({SenSys})` | `Proceedings of the 18\textsuperscript{th} Conference on Embedded Networked Sensor Systems ({sensys})` |
| wave9 | CarvEtal22b | booktitle | `Proceedings of the 20\textsuperscript{th} Annual International Conference on Mobile Systems, Applications and Services ({MobiSys})` | `Proceedings of the 20\textsuperscript{th} Annual International Conference on Mobile Systems, Applications and Services ({mobisys})` |
| wave9 | vanREtal14 | author | `G {van Rossum} and J Lehtosalo and {\L} Langa` | `G {van Rossum} and J Lehtosalo and Ł Langa` |
| wave9 | VaswEtal17 | author | `A Vaswani and N Shazeer and N Parmar and J Uszkoreit and L Jones and A N Gomez and {\L} Kaiser and I Polosukhin` | `A Vaswani and N Shazeer and N Parmar and J Uszkoreit and L Jones and A N Gomez and Ł Kaiser and I Polosukhin` |
| wave4 | BarnUnde59 | title | ````Fate'' of first-list associations in transfer theory`` | ````{F}ate'' of first-list associations in transfer theory`` (the value as cited: no change) |
| wave4 | YoneJaco97 | title | ````Response bias and the process-dissociation procedure'': correction to {Yonelinas} and {Jacoby} (1996)`` | ````{R}esponse bias and the process-dissociation procedure'': correction to {Yonelinas} and {Jacoby} (1996)`` (the value as cited: no change) |
| wave4 | ShifEtal93 | title | `{TODAM} and the list-strength and list-length effects: comment on {M}urdock and {K}ahana (1993a)` | `{TODAM} and the list-strength and list-length effects: comment on {M}urdock and {K}ahana (1993{a})` (the value as cited: no change) |
| wave6 | Dall65 | title | ````Primary memory'': the effects of redundancy upon digit repetition`` | ````{P}rimary memory'': the effects of redundancy upon digit repetition`` |
| wave7 | ShoeEtal97 | journal | `American Journal of Physiology-Heart and Circulatory Physiology` | `{American} Journal of Physiology-Heart and Circulatory Physiology` |
| wave7 | TounEtal99 | journal | `{Alzheimer} Disease and Associated Disorders` | `Alzheimer Disease and Associated Disorders` |
| wave7 | MilsEtal09 | title | `Neuronal shot noise and {B}rownian $1/f^2$ behavior in the local field potential` | `Neuronal shot noise and {B}rownian $1/{f}^2$ behavior in the local field potential` |
| wave9 | YangEtal13 | title | ````Turn on, tune in, drop out'': anticipating student dropouts in massive open online courses`` | ````{T}urn on, tune in, drop out'': anticipating student dropouts in massive open online courses`` |

## Results

Library counts come from `bibcheck.py crossref status cdl.bib`.

| Wave | Proposals | Held rows | Requests (run / repeat) | Review writes (run / repeat) | Seconds (run / repeat) | Library after |
|-|-|-|-|-|-|-|
| start | | | | | | 6,401 entries: 4,537 verified, 1,828 needs_review, 5 pending, 31 human |
| wave2 | 191: 189 edited, 19 renamed (1 rename only), 1 deleted (CronEtal94); 5 pending entries verified with it | 8 | 5 / 0 (first attempt 220) | 22 / 0 (first attempt 702) | 809 / 773 | 6,400 entries: 4,590 verified, 1,779 needs_review, 31 human |
| wave3 | 191: 188 edited, 14 renamed (1 rename only), 2 deleted (Seac97, TongEtal95) | 4 | 221 / 0 | 666 / 0 | 1076 / 756 | 6,398 entries: 4,660 verified, 1,707 needs_review, 31 human |
| wave4 | 189: 188 edited, 8 renamed (1 rename only), 0 deleted | 3 | 206 / 0 | 568 / 0 | 1003 / 744 | 6,398 entries: 4,763 verified, 1,604 needs_review, 31 human |
| wave2to4 | 15: 15 edited, 4 renamed (0 rename only), 0 deleted; needs_user resolved: ChanEtal12b -> ChanEtal12 | 0 | 19 / 0 | 56 / 0 | 797 / 739 | 6,398 entries: 4,768 verified, 1,599 needs_review, 31 human |
| wave5 | 195: 194 edited, 10 renamed (1 rename only), 0 deleted | 0 | 210 / 0 | 675 / 0 | 1008 / 733 | 6,398 entries: 4,857 verified, 1,510 needs_review, 31 human |
| wave6 | 199: 198 edited, 15 renamed (1 rename only), 0 deleted; needs_user resolved: MairEtal09a -> MairEtal09 | 0 | 215 / 0 | 674 / 0 | 1000 / 724 | 6,398 entries: 4,950 verified, 1,417 needs_review, 31 human |
| wave7 | 384: 381 edited, 35 renamed (0 rename only), 3 deleted (PailEtal00, MannEtal97, Kele99); needs_user resolved: McCaEtal06 -> McCaEtal06, LegaEtal11a -> LegaEtal11 | 0 | 478 / 0 | 1429 / 0 | 1350 / 701 | 6,395 entries: 5,084 verified, 1,280 needs_review, 31 human |
| wave8 | 206: 201 edited, 36 renamed (2 rename only), 3 deleted (KaneHash95, McGi63, Crai77) | 0 | 271 / 0 | 1000 / 0 | 1075 / 684 | 6,392 entries: 5,092 verified, 1,269 needs_review, 31 human |
| wave9 | 76: 74 edited, 12 renamed (0 rename only), 2 deleted (Weic96, WallEtal57) | 0 | 79 / 0 | 272 / 0 | 795 / 679 | 6,390 entries: 5,096 verified, 1,263 needs_review, 31 human |
