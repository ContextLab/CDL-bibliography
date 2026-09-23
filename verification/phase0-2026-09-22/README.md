# Phase 0: false flags and matcher rules (resolver 28), 2026-09-22

This phase changes code only. `cdl.bib` and `.bibcheck/verification.sqlite3`
were not modified, and no network request was made. All counts come from
`measure.py`. It opens the cache read-only (`mode=ro`), reassesses cached
evidence in memory, and loads every bibcheck module other than the Phase-0
modules from the committed `HEAD`, so other work in progress does not affect
the counts.

Plan inputs: [../resolution-plan-2026-09-22/](../resolution-plan-2026-09-22/README.md).

## Rules

`auto_review.RESOLVER_VERSION` is now 28. `POLICY` is unchanged.

| Id | Rule | Code |
|-|-|-|
| F1 | Notice, coordinate and PubMed-suffix flags are reported only for the cited work: the supplied DOI, or a candidate DOI whose Crossref title matches or is at least 0.8 similar. A DOI with no Crossref record or no title evidence keeps its flag (fail closed). Flagged DOIs are still excluded from acceptance, exactly as before. | `auto_review.cited_work_dois` |
| F2 | Byte-identical duplicate Crossref records for one DOI count as one record. Records that differ in any byte stay separate, so the DOI stays ambiguous. Applied in `pmc_coordinate_proposal`, the new article-number rule and the single-source rule. `pmc_publisher_proposal` keeps the old rule, which its existing test requires. | `auto_review.unique_crossref_primaries` |
| R1 | Print year. A Crossref candidate whose only finding is "conflicting dates" is accepted when all of these hold: `published-print` and `issued` each have exactly one date, in the cited year; any `published` date agrees; every `published-online` date is in a later year; volume and full pagination match; the record is a journal article cited as `@article`; and no DOI-linked PubMed, JATS or publisher record reports a year, coordinate or relationship problem. `compare_record` still reports the conflict. | `verification.print_year_selects_cited`, `print_year_route` |
| R2 | Duplicate DOIs. (a) Exactly two clean APA twins (`10.1037//` and `10.1037/`) with identical title, byline, venue, volume, issue and pages count as one work; the single-slash form is selected. (b) A title+author rival does not block if it is a book chapter, a posted preprint or a technical report, provided the selected journal record fully matches venue, volume and pages. (c) A rival also does not block if it is another journal-article record whose year, volume or first page is present and contradicts the citation. Rivals always block when they carry a correction relationship, are APA twins with any difference, are books or monographs, or are missing or partial. | `verification.same_clean_apa_work`, `collapse_apa_twins`, `rival_blocks` |
| R3 | Four documented journal variants, each pinned to one ISSN, with the cached Crossref and PubMed titles quoted in the code: *American Journal of Psychology* (0002-9556), the bilingual *Canadian Journal of Psychology* (0008-4255), *Lancet* (0140-6736) and *Annals of Statistics* (0090-5364). There is no fuzzy matching. Pre-1975 "JEP: General" stays a correction, not an alias. | `verification.normalize_journal` |
| A1b | Article number. The proposal sets `pages` to the article number and deletes a spurious `number` when JATS front matter and PubMed agree, and the Crossref volume agrees or is absent. The issue is kept only when JATS and PubMed agree on it. Existing pages must be empty, `1--N`, this DOI's URL, or the number itself. The edited entry must verify on the same DOI. | `pmc_corrections.pmc_article_number_proposal` |
| S1 | One authoritative source (user policy). Identity comes from one of: **I0**, the citation's own DOI; **I1**, the title within two word edits (or the citation omits the subtitle) plus first-author surname, year, venue, and either volume or first page; **I2**, exact title, first-author surname, year, volume and first page, with the venue free to differ. The rule proposes at most two differing fields, copied from the record. It holds instead when two records fit, when more than two fields differ, when PubMed holds a different value, or when the edited entry would not verify on the same DOI. | `correction_proposals.single_source_proposal` |
| S1 guards | Nothing is lost. A proposal may not drop a person, given-name detail, an accent, or case-protecting braces. It may not insert U+FFFD. It may not change a surname only by spacing, or only by deleting letters, since registries drop characters they cannot encode. Typography-only title changes are held. A venue that merely extends the cited name is held. A different venue name needs the DOI-linked PubMed title, because Crossref carries a journal's current title (e.g. "Psychiatric Services" for a 1983 *Hospital and Community Psychiatry* article). Titles are lowercase after a colon (house style), and `&amp;` becomes "and". Keys listed in earlier `*audit-exclusions.json` files stay held. | same module |
| P1 / D1 | Policy lists only; nothing is edited. P1: drop `publisher` from every `@article`. D1: add the accepted DOI to entries that verify or are corrected. | `drop_publisher_proposal`, `add_doi_proposal` |

The existing author generators (`field_proposal` and the combined
`publication_proposal`) now refuse any change that loses name detail. Before
this, they would have proposed HopkEtal12, the case its audit had excluded.

## Controls (real cached cases; `tests/test_phase0_rules.py`, 58 tests)

Fixture: `tests/fixtures/phase0_cases.json.gz` holds 42 unmodified current
review rows and their entries.

- **F1.** Positives: HarrEtal20 and BrisEtal02 lose the notice label, and GreeEtal13 loses the coordinate label. Kept: VirtEtal20, ChanEtal12b, RebeEtal02, HardEtal13, ColdEtal96b, and Murd56, whose own DOI "“Backward” learning…" carries Jr. Checked against the plan's lists: all 79 notice A/B/C keep the flag and all 80 coordinate/suffix A/B keep theirs. Of the 22 notice-M, 21 now carry only the real issue and 1 verifies. Of the 56 coordinate-C, 53 drop the label and 2 verify. Murd56 keeps its label, and the plan misclassified it.
- **F2.** Positives: BogaEtal07 and CanoEtal07. Negative: a differing copy is still ambiguous.
- **R1.** Positives: Zoll90 and MuijReyn03 (17 of the 20 P1 pilots verify). Controls that stay open: LindEtal21, BaleEtal21, StonEtal18, and six synthetic shape violations. PubMed contradictions hold Shim95, BurtBruc92 and Salt93: PubMed reports different pages or volume. The plan listed these three as positives.
- **R2.** Positives: JacoEtal92, Gros88, HakiEtal20, Este50 and Raic06. Held: Pike84, YoneJaco96a, Knut07, WainJord08 (monograph), an APA twin with a changed page or a correction flag, and a chapter rival when the article lacks pages.
- **R3.** Positive: KoleMage78. Negatives: six near-miss venue pairs.
- **A1b.** Positives: CombEtal19 and Herc09. The rule proposes 12 of the plan's 15 A1b keys, plus 3 pages-only A1a keys. Held by this rule: FoxGrei10, FiedGloc12, and KoelEtal16 (only Crossref has issue 1; the S1 rule proposes it, in S1-TWO-FIELDS-RISKY). Also held: other page shapes, and another DOI's URL.
- **S1.** Positives: CraiEtal96 (pages), KiEtal16 (title), CleeMcCl91 (surname), Game62 (I2 venue), GronEtal00 (accents added) and Knig96 (venue, PubMed agrees). Held: HopkEtal12 and CahiEtal96 (would lose names), FourEtal19 (three fields), RebeEtal02 (notice), WrigBeck83 (renamed journal), PereGran07 (accent), PlauMcCl10 (protected capitals), a duplicate record (ambiguous), and a PubMed contradiction.

Test status: the 22 owned test files pass (590 tests). The full suite
passes (1200 tests), excluding the in-flight `tests/test_pdf_evidence.py`,
which belongs to another agent.

## Measured outcome (2,753 needs_review entries)

| Outcome | Entries |
|-|-|
| Verified with no edit | **110** |
| Verified after the P1 publisher drop only | **136** |
| Correction proposals (`proposals.json`) | **387** |
| Held, grouped (`groups.json`) | **2,120** |

Rules behind the 110 verified entries (an entry can count under more than one):
APA twins 53, print year 36, chapter rivals 17, journal-article rivals 5,
preprint rivals 3, flag scope 3, journal alias 1, other 1.

### Proposal classes

| Class | n | Spot check |
|-|-|-|
| S1-TWO-FIELDS-RISKY | 80 | 20 |
| S1-AUTHOR-NAMES | 62 | 10 |
| S1-PAGES-COMPLETE | 47 | 10 |
| TWO-SOURCE | 47 | 20 |
| S1-JOURNAL-HISTORY-OR-TYPO | 33 | 10 |
| S1-TITLE-CROSSREF-ONLY | 31 | 10 |
| S1-TWO-FIELDS | 31 | 20 |
| A1b-ARTICLE-NUMBER | 15 | 15 |
| S1-COORDINATES | 13 | 10 |
| S1-TITLE-CORROBORATED | 12 | 10 |
| S1-AUTHOR-SURNAME | 10 | 10 |
| S1-JOURNAL-REPLACEMENT | 6 | 6 |
| STALE-APPROVAL-REPAIR | 10 | 10 |

Class notes:

- **TWO-SOURCE** covers the existing generators that are now unblocked.
- **STALE-APPROVAL-REPAIR** covers stored approvals that no longer reassess.
- **Publisher drop.** 85 proposals require P1 first, because they are
  evaluated with the publisher removed.
- **Row counts.** `proposals.json` has 397 rows: the 387 needs_review
  proposals and the 10 stale-approval repairs. Seven more proposals are withheld
  as audit-excluded and appear among the held entries.
- **Spot-check samples.** Each class has a seeded sample in
  `proposals.json.classes[].spot_check_keys`: 20 entries for multi-field
  classes, 10 for the others.

Policy lists:

- **P1 (drop publisher).** 1,027 `@article` entries.
- **D1 (add DOI).** 642 entries that verify or are corrected. Another 2,760
  entries that are already verified lack a DOI.

### Held groups (decision type)

**Batch decisions.** These can be answered with one decision per group, or
per journal family where noted:

| Group | Entries |
|-|-|
| More citation detail than the source (names, accents, capitals) | 303 |
| Errata on the cited work | 79 |
| Relation or update link | 61 |
| Journal title variants (about 10 journal families) | 47 |
| Issue number not in the source | 39 |
| Title typography only | 28 |
| Record type differs | 20 |
| Unverifiable extra field (`address`) | 20 |
| Online-first year | 14 |
| Jr plus a second fix | 12 |

**Individual review.** These need a human per entry:

| Group | Entries |
|-|-|
| More than two fields differ | 109 |
| Author count differs | 92 |
| Crossref and PubMed disagree | 88 |
| Other held values | 76 |
| Coordinate identity | 41 |
| Ambiguous identity | 23 |
| Other individual cases | 31 |

**Needs a new source.** 477 entries have no Crossref or PubMed record that
meets the identity rule.

**Routed to the book, chapter and proceedings plans.** 560 entries.

In round numbers, about 25 decisions plus about 160 spot-check entries would
cover the 387 proposals, the policy lists and the 623 entries in the 10 batch
groups.

## Currently verified entries (3,669)

No regression is caused by these rules:

- **Reassessment.** Every verified entry still reassesses to verified, except
  12 that already failed under the pre-Phase-0 code (checked with `--baseline`).
- **After the publisher drop.** Every verified `@article` with a publisher
  still re-verifies after P1, except 2 of those 12 (Vand00 and VaidEtal02).
- **Why the 12 fail.** They were approved under resolver 3 or earlier, when a
  citation with fewer initials than the source could still verify. That rule
  has since been tightened.
- **Repairs.** 10 of the 12 have source-backed repairs (STALE-APPROVAL-REPAIR).
  MoruMago49 and YordKole98 have ambiguous records.
- **Caution.** Any edit to these 12 entries, including P1, reopens them.

## Reproduce

```
.venv/bin/python verification/phase0-2026-09-22/measure.py --workers 8 [--baseline OLD.json]
.venv/bin/python verification/phase0-2026-09-22/measure.py --keys KEY ...   # prints rows, writes nothing
```

`--baseline` takes the output of reassessing every entry with the pre-Phase-0
code. Here that was `scratchpad/phase0/base_reassess.json`, which is not
committed. `--working-tree` loads every module from the working tree instead
of `HEAD`.

## Outside this phase's files

`docs/verification.md` still says that direct Crossref dates must collapse to
one year, and it does not describe resolver 28. The owner of that file needs
to update it.
