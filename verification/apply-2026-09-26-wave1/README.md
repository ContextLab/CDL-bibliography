# Stage 3 (2026-09-26): wave-1 research decisions and cross-wave removals

This batch applies the user's decisions recorded in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md), sections "Cross-wave
decisions" and "Wave 1 decisions" (both 2026-09-26):

- the wave-1 research results the user marked correct (`../research-2026-09-25/wave1/merged.json`, answers in
  `../research-2026-09-25/wave1/decisions/`);
- the removals the user asked for: every entry without a source, every conference abstract, the explicit
  wave-1 drops, and the extra Wechsler entries;
- the merged-away half of the 9 approved duplicates;
- the 3 approved journal-alias repairs.

The runner is [`apply.py`](apply.py). It reuses `../apply-2026-09-25f/apply.py` (on `../apply-2026-09-25e/apply.py`)
and keeps its discipline:

1. The proposals are frozen with entry fingerprints ([`wave1-proposals.json`](wave1-proposals.json), built by
   [`build.py`](build.py)).
2. The staging diff is limited to the batch, and `helpers.check_bib` must pass.
3. A backup and a snapshot go under `.bibcheck/apply-2026-09-26-wave1/`, then the batch is applied.
4. The production pipeline runs for the batch keys. A repeat run must make 0 requests and 0 review writes.
5. No accepted result outside the batch may change.
6. `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported.
7. `.bibcheck/validate-current-checkpoint.py` must give an exact fresh restore. It now reads
   [`library-changes.json`](library-changes.json) in this folder: stage 2C's removal (NetwLab25) plus this
   batch's 80, the same merged-PR additions, and `last_staged` set to this batch.
8. The full pytest suite and `verification/benchmark/run.py` (60/60) must pass, then the batch is committed.

There is one relaxation in staging. A new key may be a key that the same batch removes, because
`check_bib`'s suffix rule closes suffixes up after a removal. The reused key must then occur nowhere else in
cdl.bib.

[`log.py`](log.py) writes the key log after the batch:

- every rename and the replacement go to `../key-renames.json`, with commit `wave1`;
- every removal goes to `../key-deletions.json` (new), with its reason, decision source, date and, for a
  merge, the keeper.

Library counts come from `bibcheck.py crossref status cdl.bib` (metadata_verified / needs_review, with human_verified
and the total in brackets).

| Step | Entries | Status change in batch | Requests (run / repeat) | Review writes (run / repeat) | Library after | Commit |
|-|-|-|-|-|-|-|
| start | | | | | 4,495 / 1,955 (+31, of 6,481) | a9c7f16 |
| wave1 | 238 proposals: 157 edits (20 with a key rename), 1 replacement, 80 removals | 158 kept keys: 5 verified stay verified, +44 newly verified, none lost; 109 needs_review | 185 / 0 | 557 / 0 | 4,537 / 1,833 (+31, of 6,401) | the commit that adds this README |

The run took 1,134 s and the repeat 782 s. No accepted result outside the batch changed, and no key outside
the batch was newly verified. The details are in [`wave1-results.json`](wave1-results.json). The fresh restore gave
6,401 entries restored, 0 repeat imports and sqlite ok.

## What changed

### Wave-1 entries the user marked correct (145 edits)

- The final changes in `merged.json` are applied as proposed: 99 DOIs, 48 titles, 39 author lists, 15 entry
  types, and the rest.
- The post-check's field removals are applied too: journal on contained types, chapter moved into the title, and
  Depo18's Force.
- Held fields are not in `final_changes`, so they stay as cited.
- DougPeuc73 and Mann06 (unsure, no note) are unchanged.
- Kolo13 (unsure; "EdX should be capitalized...i think? look this up"): the Chronicle's own page prints
  `og:title" content="How edX Plans to Earn, ...` and edx.org's `<title>` is `edX | Online Courses, ...`, so the
  title uses `{edX}`.
- Wech45 (ambiguous, marked correct): only its final changes are applied (volume 19, number 1, pages 87--95).
  The identity change is held (title "A standardized memory scale for clinical use", journal, DOI
  10.1080/00223980.1945.9917223), so the entry still lacks a journal and needs the user.
- House forms that `check_bib` demands (`HOUSE_FORM` in build.py):
  - Kipp01 `({eurospeech})` and ScheEtal02 `{sigir}`: the formatter lowercases a braced acronym that is not
    in caps.txt, the same as CarvEtal22a's `({comsnets})`.
  - Tulv07: `{A}` after the colon.
  - KleiEtal07b: `Henry {L}. Roediger, {III}`. The post-check's form was garbled by the formatter.
  - Rayp68: publisher `Ferdinand {Berger}` and address `Horn, Austria`. The source prints the country, and
    `{AT}` is not an address code.
- Held because `check_bib` cannot accept them (`HELD` in build.py; they need a formatter change or a user
  decision):
  - FoodAdmi20a and FoodAdmi20b keep `Force`. It is check_bib's skip flag here; without it the formatter
    rewrites the corporate author as `{ U S Food and Drug Administration}`.
  - BirdEtal09 keeps its publisher. The publisher formatter lowercases every form of O'Reilly.
  - Galt83, Yate66 and BancEtal65 keep their country. The cross-wave rule drops an unprinted country, but the
    address formatter adds `{UK}` or `{FR}` back.

### Key renames (20, logged in `../key-renames.json` with commit `wave1`)

- The key plan follows the corrected metadata: BayeGlim07 → BayeEtal07, EchaEtal00 → EchaEtal04,
  HemmShen19 → HemmShen22, LincNati81 → Linc81, LittEtal98 → LittEtal03, LopevanL77 → LopeStor77,
  ShriEtal90 → SchrEtal90, Titc16 → Titc15, TummEtal16 → TummEtal17.
- Collisions (house suffix rule): HerrEtal09 → HerrEtal10b with HerrEtal10 → HerrEtal10a, and Frie06 → Frie08b
  with Frie08 → Frie08a. Wave 8 plans Frie08 → Frie12 (year 2012, not yet reviewed). If that is approved, Frie08a
  becomes Frie12 and Frie08b should become Frie08.
- Suffixes close up after the removals (check_bib's `check_key_suffixes`): Adey67a → Adey67,
  HealKaha14a → HealKaha14, JohnRedi07a → JohnRedi07, MannEtal09a → MannEtal09, PolyEtal05a → PolyEtal05,
  JacoEtal05d → JacoEtal05b and KahaEtal08c → KahaEtal08b.
- **The last two reuse a removed key for a different work.** A paper that cited the removed JacoEtal05b (an SfN
  abstract) or KahaEtal08b (a duplicate of KahaEtal08a) now silently cites another work.

### Replacement (1)

HealKaha14b (no source) is replaced by the published version HealKaha16: Psychological Review 123(1):23--69 (2016),
doi 10.1037/rev0000015. The entry is written in house form from its Crossref record
([`crossref/`](crossref/)), and `https://doi.org/10.1037/rev0000015` redirects (302) to doi.apa.org. HealKaha16
was not in cdl.bib. It verifies (crossref).

### Removals (80, logged in `../key-deletions.json`)

- The 16 unanswered wave-1 no_source rows (rule: any entry without a source is dropped).
- The explicit wave-1 drops: BranEtal04, ContPrev24, Gede24, GreeEtal13, HeraCE, Keck07, Land95, MerzEtal12,
  Nati24a, Nati24b and LongKaha14.
- Every conference abstract:
  - the 45 in `../research-2026-09-25/crosswave/removals.json`;
  - RamaEtal12b and SommEtal12, the SfN abstracts verified by the planner ("including SfN abstracts verified by
    the planner").
- Wechsler (user on Wech81: "pick ONE and drop the others"). cdl.bib had four Wechsler test entries:
  - Wech08 is the WAIS-IV (Crossref PsycTESTS 10.1037/t15169-000, "Wechsler Adult Intelligence Scale--Fourth
    Edition"; user: correct).
  - Wech81 is the WAIS-R (no source).
  - Wech97 is the WAIS-III (wave 9).
  - Wech45 is the Wechsler Memory Scale, a different test.

  The WAIS editions are one work, so Wech08 is kept and Wech81 and Wech97 are removed. Wech45 is kept.
- The merged-away half of the 9 approved duplicates: CronEtal98c, DawKenj06, GoenEtal08, KahaEtal08b,
  KahaMill10, LimoEtal95c, Rugg00, Wayn96 and WhitEtal96. No keeper is in wave 1, the only approved wave, so no
  keeper changes. KahaEtal08a keeps its suffix because another KahaEtal08 entry remains.

### Journal-alias repairs (3)

The values come from `../journal-alias-audit-2026-09-26.json`, and all three now verify:

- DiazEtal06 → Journal of Clinical and Experimental Neuropsychology;
- Murd68 and MurdVomS67 → Journal of Experimental Psychology.
