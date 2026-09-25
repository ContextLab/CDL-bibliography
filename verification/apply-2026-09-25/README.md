# Spot-check fixes, stage 1 (2026-09-25)

The completed spot-check produced five decisions, recorded in
[../resolution-plan-2026-09-22/README.md](../resolution-plan-2026-09-22/README.md#spot-check-completed-2026-09-2425-and-resulting-decisions).
Stage 1 fixes the rules and applies three batches with [`apply.py`](apply.py). The
batch discipline is the one used in [../apply-2026-09-23/](../apply-2026-09-23/README.md):

- proposals (or, for no-edit batches, keys) are frozen with fingerprints;
- the staging diff is limited to the batch, every cite key and the entry order are kept,
  and `helpers.check_bib` reports no errors;
- a backup and snapshot are taken under `.bibcheck/apply-2026-09-25/`;
- the production pipeline runs on the batch keys, then a repeat must make 0 network
  requests and add 0 review rows;
- no accepted result outside the batch may change;
- `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` are exported;
- the fresh-restore check (`.bibcheck/validate-current-checkpoint.py`) must restore
  all 6,422 records exactly.

## Results

| Batch | Commit | Entries | Result | Requests (run / repeat) | Library after |
|-|-|-|-|-|-|
| revert-kounios | 9cdb391 | 1 edit (`author`) | MeyeEtal88 verified → needs_review | 2 / 0 | 3,996 / 2,426 |
| rule fixes (code) | 0c321c5 | none | 38 held entries verify offline | none | unchanged |
| suffix-reassess | 98a5819 | 23, no edit | 23 / 23 metadata_verified | 0 / 0 | 4,019 / 2,403 |
| publisher-variants | 65dc998 | 15, no edit | 15 / 15 metadata_verified | 0 / 0 | 4,034 / 2,388 |

Library counts are metadata_verified / needs_review out of 6,422. The start was
3,997 / 2,425. After every step:

- the full pytest suite passed (1,274 before the rule fixes, 1,319 after);
- the benchmark (`verification/benchmark/run.py` through `run()`) was 60/60, with 0 false
  acceptances and 0 missed matches;
- the fresh restore was exact: 0 repeat imports and SQLite `quick_check` ok.

`bibcheck.py crossref status cdl.bib`: `6422 entries: metadata_verified=4034, needs_review=2388`.

## 1. revert-kounios

risky001 had copied Crossref's "J Kounois" into MeyeEtal88. The batch restores
"D E Meyer and D E Irwin and A M Osman and J Kounios". Five other entries spell the
name Kounios (AngeEtal07, JensEtal02, Koun93, Koun94, SmitKoun96), and none spells it
Kounois; the proposal records this as `library_consensus`.

After the edit MeyeEtal88 is needs_review ("No unambiguous, fully supported metadata
match"). Crossref still says Kounois. The pipeline also fetched the DOI-linked PubMed
record 3375400, which spells the name Kounios. The resolver does not accept a citation
that a Crossref record of its own DOI contradicts, so the entry waits for review. It was
not forced.

## 2. Rule fixes (commit 0c321c5, `RESOLVER_VERSION` 29)

**(a) Name suffixes are ignored on both sides.** The recognized suffixes are Jr, Sr, II,
III and IV. They no longer take part in `verification.author_evidence`,
`auto_review.compatible_authors` or `secondary_suffix_conflicts`. The same holds for a
suffix word written among the given names ("J Jr Engel", given "Alice Jr."). Any other
`jr` text in a BibTeX name is still compared.

No proposal writes a suffix:

- `house_byline` drops the source suffix;
- the catalogue `_cited_name` drops it;
- `suffix_proposal` always returns None.

PubMed suffix witnesses are still stored and exported, but they no longer block.

**(b) A cited page range is never shortened.** `correction_proposals.shortens_pages` is
true when a cited range would be replaced by its first page alone (MarmEtal78:
483--490 → 483). It is enforced in these generators:

- `pagination_proposal`, and through it the coordinate and publication generators;
- `single_source_proposal`;
- `pubmed_only_assessment`;
- the PMC coordinate and article-number generators.

Two kinds of change are not treated as shortening. A source that states a different last
page (434--443 → 434--442) corrects the range. A replacement that starts on another page
is a different correction.

**(c) A surname change needs corroboration.** This is `surname_change_hold`, where "the
same person" means the same folded surname and first initial:

- The change is held when other cdl.bib entries use the cited spelling for that person
  and none uses the proposed one (library consensus). This applies even when a second
  source agrees.
- Otherwise the change needs a second authoritative source that states the same surname,
  or other cdl.bib entries that already use the proposed spelling. With neither, it is
  held.

The check applies in `single_source_proposal`, `field_proposal` (author),
`pubmed_only_assessment`, the PMC author route and the catalogue `byline-surname-spelling`
rule.

It already holds two real cases:

- MeyeEtal88 as risky001 saw it (Crossref only): held by library consensus.
- RebeEtal02: Crossref spells D R Gitelman "Gitleman", and PallEtal03 spells him Gitelman.

Single-source fixes without corroboration are now held rather than proposed. Examples are
RacsEtal08 (Magymáté → Nagymáté) and MartJohn15 (Johnson → Johnston).

**(d) A same-firm catalogue publisher name is a match.** `catalogue_review.publisher_same_firm`
accepts a catalogue name that is a longer (or equal) form of the cited firm's name, and
the house form is kept with no edit. This covers three cases:

- every distinctive word of the cited name appears in the catalogue name
  ("Addison-Wesley" / "Addison-Wesley Pub. Co", "Erlbaum" / "L. Erlbaum Associates");
- the words run together ("Harper Prism" / "HarperPrism");
- the cited name is an acronym ("{MIT} Press").

A catalogue name that drops a cited word is not a match. For example, "Harcourt, Brace,
and World" / "Harcourt, Brace and Company" may be another firm or another era.
`compare_edition` applies the rule only when exactly one imprint publisher qualifies.

**Offline measurement** ([`measure.py`](measure.py), read-only cache, no network) re-ran
`reassess` on the 2,423 needs_review entries that have no external hold. 38 newly verify.
Each was attributed by switching its rule off again: 23 depend on the suffix rule, 15 on
the publisher rule, and 0 on anything else ([`measure.json`](measure.json)).

## 3. suffix-reassess (no edit)

All 23 entries became metadata_verified. They are the four spot-check keys (BrodMurd77,
CalvEtal73, RoedKarp06a, RoedKarp06b) and 19 more held only by a suffix: ColdEtal96b,
EricEtal13, JensRohw65, KarpRoed08, KoleRoed84, KovaEtal11, McDeEtal00, McFaEtal79,
Murd63a, Murd65, Murd67, Murd74, MurdWalk69, Roed73, RoedCrow76, SchnEtal06, TaubEtal90,
Ward61 and WyleEtal82.

## 4. publisher-variants (no edit)

All 15 entries became metadata_verified: BrunEtal02b, Carr16, Crow76, DayaAbbo01,
EfroTibs93, Gree92, Guth35, HertEtal91, Mill91, Paiv71, RussNorv95, Salt91, Sawy95,
Unde83 and Warr19. Every cited publisher is kept as written.

## Tests added or changed

Real cached cases are frozen read-only in [`cases.json.gz`](cases.json.gz), built by
[`build_cases.py`](build_cases.py) before the rule change. Each rule has negative controls.

- `tests/test_pubmed_suffixes.py`:
  - real BrodMurd77, CalvEtal73 and RoedKarp06a/b verify, and a misspelt surname still
    blocks;
  - no source suffix is written;
  - only recognized suffixes are ignored (`Jr..` and unrecognized text are not), and
    suffixes among given names or on either side are ignored;
  - given-name, surname, order, year and pages conflicts still block;
  - `suffix_proposal` returns None.
  - Updated: the old assertions that treated a suffix as identity now follow the user
    decision.
- `tests/test_correction_proposals.py`:
  - a `shortens_pages` table;
  - real MarmEtal78 and SimoEtal04 are held;
  - real AndeEtal94 (1063 → 1063--1087) is still proposed;
  - MeyeEtal88 is held by library consensus, and also by source disagreement now that the
    PubMed record is known;
  - uncorroborated MeyeEtal88 and MartJohn15 are held;
  - CleeMcCl91 is corroborated by library use of "J L McClelland" and held without it;
  - DoesEtal08 is corroborated by PubMed and held when the library spells it Kitaj.
- `tests/test_catalogue_review.py`:
  - a `publisher_same_firm` table (8 matches, 6 non-matches);
  - Crow76 and Huth13 verify with the house form;
  - Halsted Press, Koff35 and Semo23 stay needs_review;
  - Crow76, Murd74 and Huth13 expectations updated.
- `tests/test_phase0_rules.py`:
  - the suffix issue is no longer reported;
  - `house_byline` writes no suffix;
  - RebeEtal02 is held by library consensus;
  - RacsEtal08's formatted byline is checked through `source_authors`, and the proposal
    is held without corroboration.
- `tests/test_field_corrections.py` and `tests/test_dotted_initials.py`: a PubMed or cited
  suffix no longer blocks, and order and given names still do.

`.bibcheck/validate-current-checkpoint.py` now expects
`.bibcheck/apply-2026-09-25/revert-kounios-staged.bib`. `.bibcheck/` is git-ignored, so
that change is local only.

## Reproduce

```
.venv/bin/python verification/apply-2026-09-25/apply.py revert-kounios [--apply]
.venv/bin/python verification/apply-2026-09-25/build_cases.py
.venv/bin/python verification/apply-2026-09-25/measure.py
.venv/bin/python verification/apply-2026-09-25/apply.py {suffix-reassess|publisher-variants} [--apply]
.venv/bin/python .bibcheck/validate-current-checkpoint.py
```
