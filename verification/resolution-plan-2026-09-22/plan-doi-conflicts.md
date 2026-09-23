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
| B: identity suffix conflict | 14 | MED has "Jr" and the citation lacks it (all 14 are Jr; no II/III; none is part of a surname). Crossref also has Jr for 10 of them; it lacks Jr for McDoEtal10, WoodMurd68, Murd68 and MurdVomS67 |
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

- B1 (5) verify when only Jr is added, and Crossref and MED both carry Jr for all 5: ColdEtal96b, TaubEtal90, WyleEtal82, Murd67 and Ward61. Existing `suffix_proposal` refuses because Crossref also carries a year-conflict or given-name issue that MED resolves.
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

## Batches (order, sizes, success criteria)

Batches run in this order:

1. **Code-0 (no bibliography edits).** Dedupe byte-identical Crossref candidates inside the proposal generators. Add tests for identical versus differing duplicate records. Change the group-label triage to identity DOIs. Success: the full suite passes, the benchmark stays at 60/60, and approvals are unchanged.
2. **pmccoord006: 7 edits.** These are the 6 A1a entries plus KanwYove06 (journal suffix from `field_proposal`). Staging must change exactly 7 entries and keep every key. All 7 must reach `metadata_verified` with `accepted_doi` equal to the proposal DOI. The repeat must make 0 requests and 0 writes, and prior approvals must stay identical.
3. **artno001: 15 A1b edits**, after the new rule and its tests. FoxGrei10 and FiedGloc12 go in only after a publisher-page check. Success criteria are the same as batch 2.
4. **pmccoord007: 3 A1c edits** plus about 12 A2 entries whose second fix is already covered by existing Crossref+MED routes:
   - Brig12, CookEtal16 (the CookEtal16 locator conflict must be resolved first), LevyEtal00, DeadEtal13 and KhosEtal21 (if the preprint policy allows).
   - The hyphenated-initial entries: TowlEtal08, WangEtal09, MainEtal08, JungEtal08 and HansEtal12a.
   - Scha12, Fris00, ClarEtal11 and Hass07.
   - Each needs a frozen before/after, per-field source quotes, and a reassess check on the same DOI.
5. **suffix003: 5 B1 edits.** Then about 6 B2 edits combined with their second fix.
6. **Human packet (about 25).** Each item shows the citation next to the Crossref, MED and JATS values, the proposed change, and a local-PDF lead where one exists:
   - One preprint-link policy decision covering all 7 A2p entries, plus the GralFinn21 version choice.
   - Fred04 pages.
   - Missing-author and "others" bylines: SimoEtal16, AfshEtal13, NybeEtal00, FerrEtal12, SaulEtal09, MatsEtal13 and GaynEtal08.
   - Accents where the sources disagree: LismBuzs08, YlinEtal95, HeniEtal19 and DenkEtal11.
   - MoseEtal93.
   - Sparse-Crossref bylines: TianEtal03, LadoEtal02, GilbEtal10, HankEtal09, MuntEtal07 and HamiEtal09. MED is then the only complete byline source, so these need JATS or a PDF as the second source.
   - Journal replacements for Holm18 and LadoEtal02.
   - Publisher imprints for Blackwell (2 entries) and {MPRC}.
   - Print vs online years: OjemEtal09, RegeEtal18 and MuntEtal07.
   - McDoEtal10.
7. **Class C (56): no work in this group.** Hand the entries to the nomatch, author, publisher and discovery planners.

**Overall success criterion.** All 80 A and B entries end `metadata_verified` or carry a named-human adjudication record. The 56 C entries are tracked under their owning groups. Every batch repeats with 0 requests and 0 writes, all cite keys are preserved, and a fresh restore is exact.

## Per-key classification

| Key | Class | Detail (bib -> sources) | Source agreement | Route | Notes |
|-|-|-|-|-|-|
| BogaEtal07 | A1a | bib v/n/p=None/None/None -> 362/1485/1655-1670; vol-missing+pages-missing | JATS=MED=Crossref | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| CanoEtal07 | A1a | bib v/n/p=1/1/185 -> 1/1/185-196; start-page-only | JATS=MED=Crossref | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| GuggEtal07 | A1a | bib v/n/p=1/None/None -> 1/-/14; pages-missing | JATS=MED (Crossref silent) | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| VoytEtal10a | A1a | bib v/n/p=4/None/None -> 4/-/191; pages-missing | JATS=MED (Crossref silent) | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| YueEtal11 | A1a | bib v/n/p=21/1/35 -> 21/1/35-47; start-page-only | JATS=MED=Crossref | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| vandRedi09 | A1a | bib v/n/p=3/None/None -> 3/-/1; pages-missing | JATS=MED (Crossref silent) | pmc_coordinate_proposal after identical-duplicate Crossref dedupe |  |
| CombEtal19 | A1b | bib v/n/p=13/14/1--14 -> 13/-/14; artno-in-number,pages=1-N | JATS=MED=Crossref | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| FiedGloc12 | A1b | bib v/n/p=3/OCT/1--18 -> 3/-/335; e-locator-vs-pages | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) | ; bib number 'OCT' (month) deleted; article no. 335 |
| FoxGrei10 | A1b | bib v/n/p=4/10/1--13 -> 4/-/19; e-locator-vs-pages | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) | ; bib number 10 is not the article number (19); delete only after publisher-page check |
| HardEtal13 | A1b | bib v/n/p=4/159/None -> 4/-/159; pages-missing | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| Herc09 | A1b | bib v/n/p=3/31/doi.org/10.3389/neuro.09.031.2009 -> 3/-/31; pages=doi-url | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| ImboEtal19 | A1b | bib v/n/p=10/262/doi.org/10.3389/fpsyt.2019.00262 -> 10/-/262; pages=doi-url | JATS=MED=Crossref | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| JankOMar15 | A1b | bib v/n/p=9/250/1--19 -> 9/-/250; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| KoelEtal16 | A1b | bib v/n/p=6/19741/doi.org/10.1038/srep19741 -> 6/1/19741; pages=doi-url | JATS=MED=Crossref | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| MorrEtal14 | A1b | bib v/n/p=8/6/1--14 -> 8/-/6; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| MotaHerc14 | A1b | bib v/n/p=8/127/doi.org/10.3389/fnana.2014.00127 -> 8/-/127; pages=doi-url | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| PreuEtal11 | A1b | bib v/n/p=5/115/1--12 -> 5/-/115; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| ReimEtal17 | A1b | bib v/n/p=11/48/1--16 -> 11/-/48; artno-in-number,pages=1-N | JATS=MED=Crossref | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| Roll13 | A1b | bib v/n/p=7/74/1--21 -> 7/-/74; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| SeliParv10 | A1b | bib v/n/p=4/46/None -> 4/-/46; pages-missing | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| ZackEtal10 | A1b | bib v/n/p=4/168/1--15 -> 4/-/168; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | NEW article-number rule (number=artno/1--N/doi URL -> artno; drop number when no source issue) |  |
| FinkEtal96 | A1c | bib v/n/p=16/13/4275 -> 16/13/4275-4282; start-page-only | JATS=MED=Crossref | pmc route extension (tolerate advisory only if Crossref+MED both match) | start page only; JATS given-name advisory (Wolf-Dieter) |
| GoldEtal04 | A1c | bib v/n/p=24/26/6003 -> 24/26/6003-6010; start-page-only | JATS=MED=Crossref | pmc route extension (tolerate advisory only if Crossref+MED both match) | start page only; MED title punctuation (cortex/basal-ganglia) |
| StarSqui01 | A1c | bib v/n/p=None/8/190--197 -> 8/4/190-197; vol-missing | JATS=MED=Crossref | pmc route extension (tolerate advisory only if Crossref+MED both match) | volume missing (8 in number) -> 8(4); JATS given-name advisory (C E L Stark) |
| AfshEtal13 | A2 | bib v/n/p=6/117/None -> 6/-/117; pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline lists 10 of 12 (Linde, Cong missing); MED year 2012 vs Crossref 2013 |
| Brig12 | A2 | bib v/n/p=3/420/1--3 -> 3/-/420; artno-in-number,pages=1-N | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author "F D Brigard" -> F De Brigard (Crossref+MED agree); artno in number |
| ClarEtal11 | A2 | bib v/n/p=None/None/None -> 278/1709/1121-1130; vol-missing+pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | journal "Proc R Soc Lond Series B" variant; publisher |
| CookEtal16 | A2 | bib v/n/p=2016/8708434/1--9 -> 2016/-/8708434; artno-in-number,pages=1-N | JATS=MED (Crossref differs) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author B J Cook -> B L; Crossref page 1-8 vs JATS/MED artno 8708434 (sources disagree on locator form) |
| DeadEtal13 | A2 | bib v/n/p=None/None/None -> 7/-/120; vol-missing+pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author Gerhard -> Gerhardt |
| DenkEtal11 | A2 | bib v/n/p=12/None/2681--2695 -> 21/12/2681-2695; vol-differs | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | volume 12->21 (issue in volume); diacritics Lindén/Grün |
| FerrEtal12 | A2 | bib v/n/p=3/None/None -> 3/-/57; pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline ends "others" |
| Fris00 | A2 | bib v/n/p=355B/None/215--236 -> 355/1394/215-236; vol-differs | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | volume 355B->355; journal lacks "Series B" |
| GaynEtal08 | A2 | bib v/n/p=28/8/1686 -> 28/8/1686-1695; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | compound surname Doyle Gaynor; byline ends "others"; Blackwell vs Wiley |
| GilbEtal10 | A2 | bib v/n/p=4/None/None -> 4/-/30; pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author "JR" unspaced; Crossref byline sparse |
| HamiEtal09 | A2 | bib v/n/p=None/None/None -> 3/-/14; vol-missing+pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | journal missing; Crossref byline sparse |
| HankEtal09 | A2 | bib v/n/p=None/None/None -> 3/-/3; vol-missing+pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author order Hanson/Haxby swapped vs MED; umlaut Fründ; Crossref sparse |
| HansEtal12a | A2 | bib v/n/p=6/None/None -> 6/-/74; pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | M C Fellner vs Marie-Christin (hyphenated initial) |
| Hass07 | A2 | bib v/n/p=14/11/782 -> 14/11/782-794; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | publisher "Cold Spring Harbor Lab" vs "...Laboratory" |
| HeniEtal19 | A2 | bib v/n/p=6/6/None -> 6/6/eneuro.0306-19.2019; pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | citation has Buzs{\'a}ki accent sources lack; e-locator eneuro.0306-19.2019 rejected by regex |
| Holm18 | A2 | bib v/n/p=2/7/353 -> 2/7/353-384; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | journal "British Medical Journal" wrong (Br J Ophthalmol) |
| JungEtal08 | A2 | bib v/n/p=29/1193-1206/None -> 29/10/1193-1206; pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | J P Lachaux hyphenated; online 2007/print 2008; artno? pages missing |
| KanwEtal97 | A2 | bib v/n/p=17/None/4302 -> 17/11/4302-4311; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | after pages fix only residual is MED secondary-author mismatch (unexplained; diagnose) |
| LadoEtal02 | A2 | bib v/n/p=72/6/812 -> 72/6/812-815; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | journal "British Medical Journal" wrong (JNNP); Crossref byline sparse (1 author) |
| LevyEtal00 | A2 | bib v/n/p=20/None/7766 -> 20/20/7766-7775; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | author Hutchinson -> Hutchison |
| LismBuzs08 | A2 | bib v/n/p=None/None/None -> 34/5/974-980; vol-missing+pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | add 34(5):974-980; Buzsaki accent (MED has, Crossref lacks); publisher {MPRC} wrong |
| MainEtal08 | A2 | bib v/n/p=29/11/1215 -> 29/11/1215-1230; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | J P Lachaux vs Jean-Philippe (hyphenated initials); online 2007/print 2008 |
| MatsEtal13 | A2 | bib v/n/p=136/8/None -> 136/8/2444-2456; pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline ends "others" |
| MoseEtal93 | A2 | bib v/n/p=13/9/3916 -> 13/9/3916-3925; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | citation "E I Moser" has an initial neither source has |
| MuntEtal07 | A2 | bib v/n/p=1/None/None -> 1/-/11; pages-missing | JATS=MED (Crossref silent) | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | umlauts Münte/Krämer; Crossref byline sparse; Crossref print 2008 vs MED 2007 |
| NybeEtal00 | A2 | bib v/n/p=97/None/11120 -> 97/20/11120-11124; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline omits A R McIntosh (3 of 4) |
| OjemEtal09 | A2 | bib v/n/p=None/None/None -> 133/1/46-59; vol-missing+pages-missing | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | year 2009 = online; print + MED 2010 |
| SaulEtal09 | A2 | bib v/n/p=29/5/931 -> 29/5/931-942; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline ends "others"; publisher Blackwell vs Wiley (historical imprint) |
| Scha12 | A2 | bib v/n/p=1/None/7--18 -> 14/1/7-18; vol-differs | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | volume 1->14; journal typo "Neurosciences"; Crossref online 2022 vs print 2012 |
| SimoEtal16 | A2 | bib v/n/p=7/12141/1--13 -> 7/1/12141; artno-in-number,pages=1-N | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | byline lists 4 of 7 authors (Lositsky, Yeshurun, Wiesel missing) |
| TianEtal03 | A2 | bib v/n/p=74/4/433 -> 74/4/433-438; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | Crossref byline sparse (1 author); journal "&amp;" variant |
| TowlEtal08 | A2 | bib v/n/p=131/8/2013 -> 131/8/2013-2027; start-page-only | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | hyphenated initials H-A, J-P |
| WangEtal09 | A2 | bib v/n/p=None/None/10--12 -> 10/1/12; vol-missing+e-locator-vs-pages | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | hyphenated initial X-W; volume missing; pages 10--12 -> artno 12 |
| YlinEtal95 | A2 | bib v/n/p=17/None/30--46 -> 15/1/30-46; vol-differs | JATS=MED=Crossref | coordinate fix + second correction (author/journal/publisher/year) via existing field/author/journal routes, then reassess | volume 17->15; accents Nádasdy/Jandó/Szabó (MED) vs none (Crossref) |
| ChanEtal21a | A2p | bib v/n/p=7/17/doi.org/10.1126/sciadv.abf7129 -> 7/17/eabf7129; pages=doi-url | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | pages doi URL->eabf7129 (regex rejects e-prefix >3 letters); hyphenated initials P-H A; MED "Preprint in" |
| GralFinn21 | A2p | bib v/n/p=doi.org/10.31234/osf.io/c8z9t/None/None -> 17/6/598-608; vol-differs+pages-missing | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | cites PsyArXiv preprint; DOI-linked journal version SCAN 17(6):598-608 (2022): VERSION CHOICE |
| KhosEtal21 | A2p | bib v/n/p=8/22/doi.org/10.1126/sciad.abe7547 -> 7/22/eabe7547; vol-differs+pages=doi-url | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | volume 8->7, pages doi URL->eabe7547; author Kuceveski->Kuceyeski; MED "Preprint in" |
| LindEtal19 | A2p | bib v/n/p=10/179/1--13 -> 10/1/179; artno-in-number,pages=1-N | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | number=artno 179; MED "Preprint in" |
| McInJirs19 | A2p | bib v/n/p=doi.org/10.1162/netn\_a\_00107/None/None -> 3/4/994-1008; vol-differs+pages-missing | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | volume holds DOI URL; set 3(4):994-1008; MED "Preprint in" |
| OwenEtal21 | A2p | bib v/n/p=12/5728/doi.org/10.1038/s41467-021-25876-x -> 12/1/5728; pages=doi-url | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | pages doi URL->5728; number 5728->1? (JATS none, Crossref 1); MED "Preprint in" |
| RegeEtal18 | A2p | bib v/n/p=None/None/None -> 29/10/4017-4034; vol-missing+pages-missing | JATS=MED=Crossref | HUMAN policy: MED "Preprint in"/Crossref has-preprint link | add 29(10):4017-4034; year 2018 online vs 2019 print/MED; MED "Preprint in" |
| Fred04 | A2x | bib v/n/p=359/1449/None -> 359/1449/1367-1378; pages-missing | JATS=MED (Crossref differs) | HUMAN: sources disagree on end page | JATS+MED 1367-1378 vs Crossref 1367-1377: SOURCES DISAGREE |
| ColdEtal96b | B1 | J Engel -> Engel J Jr | MED Jr = Crossref Jr (both agree) | suffix_proposal variant (Jr from DOI-linked MED fullName; accept only if reassess verifies same DOI) |  |
| Murd67 | B1 | B B Murdock -> Murdock BB Jr (+1 more) | MED Jr = Crossref Jr (both agree) | suffix_proposal variant (Jr from DOI-linked MED fullName; accept only if reassess verifies same DOI) |  |
| TaubEtal90 | B1 | J B Ranck -> Ranck JB Jr | MED Jr = Crossref Jr (both agree) | suffix_proposal variant (Jr from DOI-linked MED fullName; accept only if reassess verifies same DOI) |  |
| Ward61 | B1 | A A Ward -> WARD AA Jr | MED Jr = Crossref Jr (both agree) | suffix_proposal variant (Jr from DOI-linked MED fullName; accept only if reassess verifies same DOI) |  |
| WyleEtal82 | B1 | A A Ward -> Ward AA Jr | MED Jr = Crossref Jr (both agree) | suffix_proposal variant (Jr from DOI-linked MED fullName; accept only if reassess verifies same DOI) |  |
| BrunHaus03 | B2 | J Bruns -> Bruns J Jr | MED Jr = Crossref Jr (both agree) | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| DiazEtal06 | B2 | S J Potolicchio -> Potolicchio SJ Jr | MED Jr = Crossref Jr (both agree) | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| McDoEtal10 | B2 | Donald J Hagler -> Hagler DJ Jr | MED Jr; Crossref lacks suffix | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| MullEtal87 | B2 | J Ranck -> Ranck JB Jr | MED Jr = Crossref Jr (both agree) | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| MullEtal96 | B2 | J Ranck -> Ranck JB Jr | MED Jr = Crossref Jr (both agree) | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| Murd68 | B2 | B B Murdock -> Murdock BB Jr | MED Jr; Crossref lacks suffix | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| MurdVomS67 | B2 | B B Murdock -> Murdock BB Jr | MED Jr; Crossref lacks suffix | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| QuirEtal92 | B2 | James B Ranck -> Ranck JB Jr | MED Jr = Crossref Jr (both agree) | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| WoodMurd68 | B2 | A Woodward -> Woodward AE Jr (+1 more) | MED Jr; Crossref lacks suffix | Jr + second correction (given names/journal/issue/byline), then reassess |  |
| GreeEtal13 | C0 | rival 10.1093/cercor/bhs229 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| KragEtal17 | C0 | rival 10.1073/pnas.97.20.11120 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| LongEtal10 | C0 | rival 10.1371/journal.pbio.2005479 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| MackEtal20 | C0 | rival 10.1371/journal.pbio.2005479 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| MannEtal97 | C0 | rival 10.1523/jneurosci.22-13-05694.2002 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| MasiEtal22 | C0 | rival 10.1073/pnas.97.20.11120 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| Murd56 | C0 | rival 10.1037/h0023113 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| Murd62b | C0 | rival 10.1037/h0046262 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| NateEtal06 | C0 | rival 10.1371/journal.pone.0134561 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| RaghEtal99 | C0 | rival 10.1523/jneurosci.21-09-03175.2001 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| TallEtal97 | C0 | rival 10.1523/jneurosci.18-11-04244.1998 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| WageSmit03 | C0 | rival 10.1073/pnas.95.20.12061 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| Yone96 | C0 | rival 10.1523/jneurosci.5295-04.2005 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| vanGEtal13 | C0 | rival 10.1093/cercor/bhs229 | n/a (flag from unrelated DOI) | re-route: articles_nomatch/discovery (no identity DOI) |  |
| AbdeEtal21 | C1 | rival 10.1523/jneurosci.2798-18.2019; identity 10.2139/ssrn.4044117: journal, publication type/version is unsupported or differs, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| AlyTurk16 | C1 | rival 10.1523/jneurosci.0360-19.2019; identity 10.1073/pnas.1518931113: author, pages | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| AshbEtal96 | C1 | rival 10.1098/rstb.1998.0284; identity 10.1037//0033-295x.103.1.165: publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BarrEtal06 | C1 | rival 10.1016/j.tins.2013.12.003; identity 10.1515/revneuro.2006.17.1-2.71: author, pages | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BarrEtal12b | C1 | rival 10.1016/j.tins.2013.12.003; identity 10.1038/nature11276: pages, publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BlasEtal96 | C1 | rival 10.1523/jneurosci.22-13-05694.2002; identity 10.55782/ane-1996-1116: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BostEtal91 | C1 | rival 10.1523/jneurosci.14-12-07235.1994; identity 10.1002/hipo.450010207: year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BragEtal95 | C1 | rival 10.1523/jneurosci.15-01-00030.1995; identity 10.1523/jneurosci.15-01-00047.1995: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BrunEtal02a | C1 | rival 10.1523/jneurosci.12-05-01945.1992; identity 10.1126/science.1071089: author, pages | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BurgEtal01b | C1 | rival 10.1098/rstb.1997.0130; identity 10.1098/rstb.2001.0948: author, journal | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| BurgOKee96 | C1 | rival 10.1016/j.tins.2013.12.003; identity 10.1002/(sici)1098-1063(1996)6:6<749::aid-hipo16>3.0.co;2-0: number, volume | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| CaplEtal00 | C1 | rival 10.1523/jneurosci.21-09-03175.2001; identity 10.1016/s0925-2312(00)00229-0: author, volume | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| ChenEtal17 | C1 | rival 10.1093/cercor/bhx202; identity 10.1038/nn.4450: Source has related versions/works; review publication i, pages, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| FaboEtal08 | C1 | rival 10.1093/brain/awt159; identity 10.1093/brain/awm297: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| GellEtal14 | C1 | rival 10.1093/cercor/bhs229; identity 10.1016/j.clinph.2014.01.021: author, number, pages, volume | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| HankEtal08 | C1 | rival 10.3389/neuro.11.003.2009; identity 10.1007/s12021-008-9041-y: number, pages, volume, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| HerrEtal09 | C1 | rival 10.1523/jneurosci.19-16-07152.1999; identity 10.1016/j.neubiorev.2009.09.001: number, pages, volume, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| HowaEtal03 | C1 | rival 10.1523/jneurosci.21-09-03175.2001; identity 10.1093/cercor/bhg084: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| KafkMont15 | C1 | rival 10.1177/2041669519874817; identity 10.1111/psyp.12471: publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| KanwYove06 | C1 | rival 10.1523/jneurosci.17-11-04302.1997; identity 10.1098/rstb.2006.1934: journal | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| LachEtal03 | C1 | rival 10.1002/hbm.20454; identity 10.1016/j.jphysparis.2004.01.018: author, journal | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| LachEtal07a | C1 | rival 10.1002/hbm.20454; identity 10.1002/hbm.20352: author, number, pages, volume | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| LiEtal19 | C1 | rival 10.1038/s41467-019-10317-7; identity 10.1016/j.neuroimage.2019.04.016: Source has related versions/works; review publication i | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| LlinEtal98 | C1 | rival 10.1098/rstb.1998.0335; identity 10.1098/rstb.1998.0336: author, journal | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| MaguEtal00 | C1 | rival 10.1523/jneurosci.17-18-07103.1997; identity 10.1073/pnas.070039597: pages | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| MeshEtal21 | C1 | rival 10.1093/scan/nsab103; identity 10.1038/s41467-021-22202-3: Source has related versions/works; review publication i, author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| Murd76 | C1 | rival 10.1037/h0025694; identity 10.1037//0096-3445.105.2.191: clean (double-slash DOI pair) | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| NguyEtal23 | C1 | rival 10.1523/eneuro.0306-19.2019; identity 10.1038/s41598-023-43975-1: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| PentEtal98 | C1 | rival 10.1523/jneurosci.15-01-00030.1995; identity 10.1046/j.1460-9568.1998.00096.x: author, publisher, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| RangDEsp01 | C1 | rival 10.1523/jneurosci.1337-10.2010; identity 10.1016/s0896-6273(01)00411-1: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| RubiEtal17 | C1 | rival 10.1093/cercor/bhs065; identity 10.1371/journal.pcbi.1005649: Source flags an update/correction/retraction relationsh, Source has related versions/works; review publication i, author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| SchaEtal18 | C1 | rival 10.1523/jneurosci.0257-12.2012; identity 10.1093/cercor/bhx179: Source has related versions/works; review publication i, author, year | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| Schu05 | C1 | rival 10.1523/jneurosci.17-11-04302.1997; identity 10.1016/j.ijdevneu.2004.12.012: publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| SedeEtal10 | C1 | rival 10.1523/jneurosci.2312-17.2018; identity 10.3758/mc.38.6.689: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| Sing98 | C1 | rival 10.1098/rstb.1998.0336; identity 10.1098/rstb.1998.0335: author, journal, publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| SmitEtal98 | C1 | rival 10.1073/pnas.95.20.12061; identity 10.1073/pnas.95.3.876: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| SmitJoni98 | C1 | rival 10.1073/pnas.95.3.876; identity 10.1073/pnas.95.20.12061: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| TallEtal01 | C1 | rival 10.1523/jneurosci.18-11-04244.1998; identity 10.1523/jneurosci.21-20-j0008.2001: number, pages | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| TothAssa02 | C1 | rival 10.1111/j.1460-9568.2009.06635.x; identity 10.1038/415165a: publisher | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| WeisEtal00 | C1 | rival 10.1073/pnas.1014528108; identity 10.1097/00001756-200008030-00005: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| WiebStau01 | C1 | rival 10.1523/jneurosci.6305-10.2011; identity 10.1523/jneurosci.21-11-03955.2001: author, number | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
| YeoEtal11 | C1 | rival 10.1093/cercor/bhx179; identity 10.1152/jn.00338.2011: author | n/a (flag from unrelated DOI) | re-route to group of identity-DOI blocker |  |
