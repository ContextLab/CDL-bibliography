# Plan: DOI-linked coordinate and suffix conflicts (136 entries)

Written 2026-09-22 by a read-only planning agent. Nothing in cdl.bib, the main cache or any tracked file was changed. No network requests were made.

All evidence comes from the current-fingerprint policy-2 review in `.bibcheck/verification.sqlite3` (read-only). Analysis scripts and outputs are in `scratchpad/doiconf/`:

- `extract.py` → `extract.json`: per-DOI Crossref, MED and JATS values.
- `classify.py` → `identity_rows.json`.
- `proposals.py` and `proposals_dedup.py`: every existing proposal generator, run offline.
- `simulate.py` → `simulate.json`: reassessment after an ideal coordinate fix.
- `suffix_sim.json`: reassessment after adding the PubMed Jr.
- `nonident.json`, `diag.json`, `authdiff.txt`, `table.json`.

## How the flag is produced (important)

- `auto_review.select_result` adds the coordinates issue when `source_locators.locator_conflicts` finds **any** candidate DOI that meets all of these conditions:
  - It has a pmc-jats record.
  - Its JATS front-matter volume/page agrees with the DOI-linked MED record.
  - That volume/page differs from the citation.
- It adds the suffix issue when **any** DOI-linked MED record has a Jr/II/III that the citation's matching surname lacks.
- The flag is not limited to the cited work's DOI. It also fires for rival DOIs that discovery collected, such as a different paper by the same authors.
- By construction, publisher JATS and PubMed always agree with each other in the coordinate class. Only Crossref can disagree.

## Class counts

| Class | n | Meaning |
|-|-|-|
| A: identity coordinate conflict | 66 | The conflicting DOI is the cited work (Crossref title matches) |
| B: identity suffix conflict | 14 | MED has "Jr" and the citation lacks it (all 14 are Jr; no II/III; none is part of a surname) |
| C: label-only (rival DOI) | 56 | The flag comes only from an unrelated work's DOI; the real blockers are elsewhere |

### Class A subclasses (66)

The conflict types are:

- 16 start-page-only.
- 14 pages missing.
- 11 article number in `number` with `pages=1--N` (page count).
- 8 volume and pages missing.
- 6 pages holding a doi.org URL.
- 4 wrong volume, for example `355B`, `17`→15, `12`→21 (issue in the volume field), and `1`→14.
- 2 wrong volume with pages missing, where the volume field holds a DOI URL.
- 4 other e-locator cases.
- 1 volume missing.

Source agreement:

- JATS = MED = Crossref: 41.
- Crossref silent (sparse Frontiers-style deposit): 23.
- **Crossref differs: 2.** Fred04 has an end page of 1378 in JATS and MED but 1377 in Crossref. CookEtal16 has article number 8708434 in JATS and MED but Crossref gives "1-8".

A simulated coordinate-only fix (volume and pages from JATS and MED; issue from Crossref, or `number` dropped when no source has one) was followed by offline `reassess()`. Results:

- **A1: 24 would verify from the coordinate fix alone.**
  - A1a (6): the existing `pmc_coordinate_proposal` already produces the exact edit once one mechanical blocker is removed. See the key finding below.
  - A1b (15): a new article-number rule is needed. The citation's `number` equals the article number (or is spurious: FoxGrei10 `10`, FiedGloc12 `OCT`) and must be **deleted**, because Frontiers, Nature Communications and Scientific Reports JATS have no issue. `pmc_coordinate_proposal` refuses to empty a field. Precedents are pmccoordinates HargEtal12 (DOI URL → article number) and coordinates-batch ZhanEtal18a/EzzyEtal18 (number=article number → issue 1).
  - A1c (3): StarSqui01, FinkEtal96 and GoldEtal04 are blocked in the pmc route by a JATS given-name advisory or MED title punctuation, although `reassess` verifies them.
- **A2: 34 need the coordinate fix plus a second correction.** Details are in the table:
  - Author: 27. These include true citation errors: De Brigard, Hutchison, Gerhardt, Kuceyeski, and B L Cook. Also:
    - Missing authors: SimoEtal16 has 4 of 7, AfshEtal13 10 of 12, NybeEtal00 3 of 4.
    - "others" truncation: 4 entries.
    - Hyphenated initials: 5.
    - Diacritics: 4.
    - Sparse Crossref bylines (first author only): 5.
  - Journal: 7. Holm18 and LadoEtal02 are wrongly "British Medical Journal", and Scha12 has a typo.
  - Publisher: 6. Blackwell vs Wiley counts as a historical imprint.
  - Print vs online year: 5.
- **A2p: 7 are blocked by a MED "Preprint in" (PPR) link plus Crossref `has-preprint`:** KhosEtal21, GralFinn21, OwenEtal21, McInJirs19, RegeEtal18, LindEtal19 and ChanEtal21a. Resolver 19 treats only Comment in/on as benign.
- **A2x: Fred04 has sources that disagree.**

### Class B (14)

- B1 (5) verify when only Jr is added: ColdEtal96b, TaubEtal90, WyleEtal82, Murd67 and Ward61. Existing `suffix_proposal` refuses because Crossref also carries a year-conflict or given-name issue that MED resolves.
- B2 (9) need Jr plus another fix:
  - Ranck "J" → "J B": MullEtal96, MullEtal87, QuirEtal92.
  - Journal variant: Murd68, MurdVomS67, WoodMurd68.
  - DiazEtal06: journal and year.
  - BrunHaus03: supplement issue.
  - McDoEtal10: byline count, and its JATS is an author manuscript.

### Class C (56)

- C0 (14): no identity DOI at all, because only rival DOIs were found. These belong with the articles_nomatch, discovery and local-PDF work. Examples: Yone96 (a dissertation abstract), SfN abstracts, and Murd56/Murd62b.
- C1 (42): the identity DOI exists but is blocked by something else. The main blockers are author (20), publisher (6), Crossref-only pages/volume (about 10, for example AlyTurk16 E-prefix and TallEtal01 RC177), preprint links, and double-slash DOI pairs (Murd76, AshbEtal96).
- **No coordinate work applies to class C.** The flag is misleading.

## Key finding: identical duplicate Crossref candidates block the PMC route

All 66 class-A entries carry **two byte-identical Crossref candidates** for the cited DOI, because discovery reruns appended a copy. `pmc_coordinate_proposal` requires `len(primaries) == 1` and so silently returns nothing.

The existing generators were run offline on all 136 entries:

- As they stand, only 2 proposals come back: BogaEtal07 through `coordinate_proposal`, and KanwYove06 through `field_proposal('journal')`.
- With exact-duplicate Crossref records collapsed (same DOI and identical `record` JSON), `pmc_coordinate_proposal` also produces the 6 A1a edits.

Collapsing byte-identical records does not loosen matching. Records that differ must still be refused.

## Routes

| Subclass | n | Route | Human? |
|-|-|-|-|
| A1a | 6 | Fix `pmc_coordinate_proposal`/`coordinate_proposal` to dedupe identical Crossref records, then use the existing `pagination.py --batch pmccoordinatesNNN` pattern | No |
| A1b | 15 | NEW `pmc_article_number_proposal`, described below | Spot-check FoxGrei10 and FiedGloc12 (see the questions below) |
| A1c | 3 | Extend the pmc route: tolerate a JATS given-name advisory or MED title-punctuation issue only if both Crossref and MED author/title evidence match the proposed entry and `reassess` accepts the same DOI | No |
| A2 | 34 | Coordinate fix and the second fix in one frozen proposal. Author/journal/publisher fixes need Crossref and MED agreement (existing `field_proposal`/`publication_proposal(include_identity_fields=True)` and `pmc_names` logic). Anything where Crossref is sparse or disagrees goes to documentary (PDF) review | Author additions (SimoEtal16, AfshEtal13, NybeEtal00, "others" ×4), MoseEtal93, HeniEtal19/LismBuzs08 accents, Blackwell→Wiley, OjemEtal09 year |
| A2p | 7 | Policy decision on MED "Preprint in" | Yes, one policy decision; GralFinn21 also needs a version choice |
| A2x | 1 | Fred04: compare the publisher PDF (local library or publisher page) | Yes |
| B1 | 5 | `suffix_proposal` variant: take Jr from the exact DOI-linked MED fullName, and keep the proposal only if `reassess` verifies the same DOI. Format `Surname, Jr, Given` (precedent: `Murdock, Jr, B B` already in cdl.bib) | No (policy already adopted: 48 suffix records) |
| B2 | 9 | Jr combined with a given-name, journal or issue fix | McDoEtal10 byline |
| C0/C1 | 56 | Re-route to the owning groups. Optionally make the group label report the coordinate or suffix issue only when the conflicting DOI is the identity candidate (reporting only; `good` selection unchanged) | Per the other groups |

### NEW rule: article number (A1b, and the coordinate part of A2)

Propose `pages = <article number>` and delete `number` only if **all** of these hold:

1. There is exactly one DOI-linked JATS record, and its top-level `elocation-id`/article number equals the MED `pageInfo`. `source_locators._coordinates` already enforces this.
2. JATS, MED and Crossref volume all equal the proposed volume, or Crossref volume is absent.
3. No source supplies an issue. If Crossref supplies one and JATS does not, set `number` to Crossref's issue only when MED's issue equals it, or when MED has no issue and the precedent from the coordinates batch applies. Otherwise hold for a human.
4. The current `pages` value is empty, `1--N`, a doi.org URL of the **same DOI**, or a start page equal to the JATS first page.
5. Title and ordered byline already match (unchanged identity).
6. The fully proposed entry passes `assess_fulltext` with no issues, and `reassess` returns `metadata_verified` for the same DOI.
7. The e-locator regex stays as it is. Extend it only for `e`+letters such as `eabe7547`/`eabf7129` and the eNeuro form, and only with explicit tests.
