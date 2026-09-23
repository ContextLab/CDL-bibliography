# Plan: 1,945 @article entries with "No unambiguous, fully supported metadata match"

Prepared 2026-09-22 (read-only planning pass). Nothing in `cdl.bib`, the cache, or any
tracked file was changed.

## 0. How this was measured

- Input: `scratchpad/group-articles_nomatch.json` (1,945 keys).
- For **every** key (not a sample) I read the latest `reviews` row from
  `.bibcheck/verification.sqlite3` (opened `mode=ro`). All 1,945 are
  `status: needs_review`, policy `2`; the cached fingerprints equal the current
  `load_entries('cdl.bib')` fingerprints (checked for the 513 T3 keys: 0 mismatches).
- Per entry I chose the "best" Crossref candidate (max difflib title similarity
  + 0.3 if first-author surname equals) and read its **cached per-candidate
  `issues` and `evidence`** (the exact strings produced by `compare_record`).
  Europe PMC (`source: europepmc`) candidates were matched to the same DOI.
- About 150 entries were inspected by eye across all classes (examples quoted
  below). Counts are full-population counts from the cache, not extrapolations,
  except where marked "estimate".
- Hypothetical matcher rules were simulated **offline** on the cached evidence
  (`scratchpad/simulate.py`), and the existing proposal generators
  (`correction_proposals.pagination_proposal` / `field_proposal`) were run
  read-only on the 513 T3 entries.
- Network: 9 requests total (8 PubMed ESearch + 1 ESummary), paced ≥1.5 s,
  `tool=cdl-bibcheck-planning`, no email parameter.
- Scratch outputs: `nomatch-results.json` (cached results), `nomatch-classified.json`,
  `tiers.json` (key lists per tier below), `sim-keys.json`, `probe-pubmed.json`,
  `t3-existing-proposals.json`.

Why the pipeline stops (from `bibcheck/verification.py`): with no `doi` field,
`verify_entry` accepts only if exactly one Crossref search candidate has **zero**
issues and no *rival* (another DOI whose title and author also match). Otherwise
it falls through to "No unambiguous, fully supported metadata match". Only 17 of
the 1,945 have a `doi` field. Europe PMC was queried **only by the Crossref
candidate's exact DOI** (`auto_review`: "Missing identifiers are not guessed"),
so 909/1,945 entries have no PubMed evidence at all.

## 1. Failure taxonomy (full population, n = 1,945)

Tiers are mutually exclusive and sum to 1,945 (`tiers.json`).

| Tier | n | What blocks acceptance |
|-|-|-|
| T1 matcher-only | 118 | Best candidate fully matches except a date-semantics flag or rival rule (details in 1a) |
| T2 publisher-only | 123 | Only `publisher` differs, and it is a historical imprint vs. the current owner |
| T3 one field; PubMed disagrees with the citation too | 513 | Citation likely wrong in one field; both sources say so |
| T4 one field; PubMed agrees with the citation or is otherwise inconclusive | 60 | Crossref vs PubMed conflict / relation / update flags |
| T5 one field; no PubMed record | 302 | One field differs; only Crossref speaks |
| T6 two or more fields differ | 671 | 2 fields: 467; 3: 124; 4: 38; 5: 22; 6: 13; 7: 7 |
| Z no plausible Crossref candidate | 158 | Title similarity < 0.75 or first author differs, title < 0.9 |

### 1a. T1 (118): matcher-semantics blockers, no citation error

- **R1 retro-digitized print year (≈40 entries alone).** Crossref gives several
  years, so `compare_record` adds "year: conflicting or missing publication dates;
  select the cited edition explicitly". Example: `Zoll90` matches every field
  including its DOI, but Crossref reports `published-print [1990]`, `issued [1990]`,
  `published-online [2011]`. Over all plausible candidates, 147 year flags have
  exactly this shape: print = issued = cited year, online ≥3 years later. Another
  57 have print = cited and online 1–2 years earlier (`LindEtal21`: online 2020,
  print 2021). 24 have online = cited and print later (`BaleEtal21`). 65 have the
  cited year absent from Crossref (35 off by one, 30 off by ≥2).
- **R2 rival rule (≈75).** A fully matching candidate exists but another DOI
  also matches title and author:
  - 54 are APA doubled-slash twins (`JacoEtal92`: `10.1037//0003-066x.47.6.802`
    and `10.1037/0003-066x.47.6.802`).
  - 16 are book-chapter reprints (`Gros88` → `10.7551/mitpress/5271.003.0004`).
  - 3 are PsyArXiv preprints (`HakiEtal20`, `Niv21`, `Rang19`).
  - 3 are other journal articles with a conflicting year, volume or pages
    (`Raic06` vs a 2010 *Scientific American* piece; `Este50` vs the 1994
    *Psych Review* reprint `10.1037/0033-295x.101.2.282`).
  - Correct negative controls: `Pike84` and `YoneJaco96a`. There, the twin
    carries "Source flags an update/correction/retraction relationship", so they
    must stay blocked.
  - Caution: in `Knut07`, two same-journal DOIs exist for one article
    (`10.1519/00124278-200708000-00053` and `10.1519/r-505011.1`; the latter's
    record has only first page 973). This is a duplicate registration, not a
    different work. It should be held, not auto-cleared.
- **R3 exact journal-title variants (4).** Examples: `AvraEtal97`, `Colt81`,
  `KoleMage78`. The pattern is `{American} Journal of Psychology` vs "The American
  Journal of Psychology", and "Canadian Journal of Psychology" vs "Canadian
  Journal of Psychology / Revue canadienne de psychologie".

### 1b. T2 (123): publisher field

Exact pairs from the cached `evidence.publisher`:

| Citation | Crossref | Count |
|-|-|-|
| Nature Publishing Group | Springer Science and Business Media LLC | 42 |
| Springer | Springer Science and Business Media LLC | 18 |
| Psychonomic Society | Springer Science and Business Media LLC | 10 |
| Taylor and Francis Group | Informa UK Limited | 5 |
| Nature America | Springer Science and Business Media LLC | 5 |
| Blackwell | Wiley | 4 |

`normalize_publisher` explicitly refuses "acquisitions or historical imprints".
Including multi-field entries, 107+ entries list `publisher` among their blockers.

### 1c. Author discrepancies (753 entries have `author` among blockers; T3 240, T5 115)

Subtypes, computed on the first differing author against the best Crossref record:

| Subtype | n (all) | Examples | Direction |
|-|-|-|-|
| Citation has MORE given names/initials than the source | 155 | `Wask21` "Michael L" vs "Michael"; `ChiEtal01` "R G M" vs "Robert G." | Source incomplete |
| Citation has FEWER initials than the source | 134 | `LuriEtal18` "D" vs "Daniel J"; `Box76` "G" vs "George E. P." | Citation incomplete |
| Surname spelling differs | 116 | `ZhanEtal18b` Kozereva/Kozareva; `StopEtal07` Shoenfeld/Schoenfeld; `CleeMcCl91` McCleeland (PubMed and Crossref both say McClelland); `IntrPoli94` Intrilligator | Mostly citation typos |
| Surname partial, compound, or particle split | 66 | `vandEtal11` Crossref family "Pol", given "Janneke van de"; `GranWals16` "Busby Grant"; `RhoaEtal13` "Berdan," | Often a Crossref defect |
| Accents missing in the citation | 56 | `FourEtal19` Huszar/Huszár; `GronEtal00` Gron/Grön; `BasaEtal99` Basar/Başar | Citation incomplete |
| Author count differs | ~125 | 52 differ by ≥3, e.g. `LindEtal21` 19 vs Crossref's count | Either side |
| Citation has the full name, source has only an initial | 31 | `HopkEtal12` "Michael E" vs "M.E." | Source incomplete |
| Given names conflict | 26 | `WhitWang83` | Needs a document |
| Suffix | 24 | `RoedCrow76`, `Murd65` (Jr) | Either side |

### 1d. Title discrepancies (396 plausible entries have `title` among blockers)

| Subtype | n | Examples |
|-|-|-|
| Punctuation or spacing only | 133 | `PosnEtal87` missing "?"; `ThorTami20` "happen:psychological" (no space) |
| Single-word typo or variant | 101 | `BeamJone98` "reacall"; `WangGuo19` "anlysis"; `KiEtal16` "stronly"; `BlayEtal06` Category/Categorical |
| Citation truncated (source has a subtitle) | 39 | `Ragl90`, `EtzeEtal09` ("... classification analysis") |
| Multi-word differences | 44 | `ScanEtal21` "Biomarkers of..." vs "Distributed Subnetworks of..." (possibly the preprint title); `PetrPand94` looks like the wrong candidate |
| Citation LaTeX/math not parseable by `normalized()` | 17 | `ThutEtal06` `$\alpha$`; `GusmEtal14` `\textregistered` |
| Source markup (`<sub>`, `<sup>`, `<i>`) | ~5–10 | `HariEtal03`, `GammEtal04`, `GrunEtal99` |
| Source adds a heading prefix | ~5 | `RacsEtal08` "Short Article:"; `HallWals02` "10."; `MayeEtal92b` "Chapter 4" |
| Accent-only | 6 | `BartEtal04a` deja vu/déjà vu; `VonR33` Uber/Über |
| Source shorter (missing subtitle) | 6 | `SanbGrif08` |

### 1e. Journal discrepancies (337 plausible entries have `journal` among blockers)

- **Anachronistic "JEP: General" (50).** Every cited year is ≤1974 (for example
  `Game62`, `HilgEtal53`, `HoroEtal64`), but *JEP: General* began in 1975. PubMed
  PMID 13896567 for `Game62` says "J Exp Psychol", 1962;63:1-11. This is a
  citation error. The existing `JEP_HISTORY` / `journal_history_proposal` already
  encodes this history.
- **"Psychological Science" for 1965–1970 (12).** The source is *Psychonomic
  Science*, a citation error. These records also carry Springer backfile years
  (`Muth65` source years `['1965','2014']`).
- **Citation typos (~20).** Examples: "Phychophysiology", "Behavioral Brain
  Research" (source: Behavioural), "Physiological Review" (Reviews), "Americal
  Journal", "Journal of the Acoustic Society".
- **Wrong or truncated venue (~15).** "Learning and Memory" for JEP:LMC articles
  (`AndeFinc94`, `NaveEtal03`, `Brow97`); "Journal of Verbal Learning..." cited
  for a JEP record.
- **Title variants (~45).** QJEP "Section A"; "Electroencephalography and Clinical
  Neurophysiology/Evoked Potentials Section"; "Philosophical Transactions ...
  Series {B}" forms; "The Lancet"; "The Annals of Statistics"; bilingual Canadian
  titles.

### 1f. Pages, volume and number (plausible entries)

- **Pages (425).**
  - 179 share the start page but differ at the end. This covers genuine
    end-page errors (`CraiEtal96` 159--179: Crossref and PubMed both give
    159-180) and Cell-style `.e13` suffixes (`HamiEtal21` `4626-4639.e13`).
  - 77 have the field missing locally.
  - 65 are "different". Many are DOI URLs stored in `pages`
    (`WeisEtal16` "doi.org/10.1186/s40537-016-0043-6") or invented ranges
    alongside an article number (`NastEtal20` pages `117254--117261`, source
    article number `117254`).
  - 57 are cases where the source gives only the first page.
- **Volume (238).** 136 differ, 53 are missing locally, and 49 are missing in
  the source. Several are article numbers or DOIs in the wrong field
  (`Finn21` volume = "doi.org/10.1016/j.tics.2021.09.005").
- **Number (339).** 256 are "missing locally". These are advisory unless volume
  or pages also fail.

### 1g. Z: no plausible Crossref candidate (158)

- 33: Crossref holds only the main title, and the citation adds a subtitle
  (`AharEtal01`, `DaleEtal00`, `DobbEtal02`; Neuron accounts for 14 of the 158).
  These are really title-subtitle cases.
- 44: non-DOI or grey venues typed as @article (NeurIPS, JMLR, PMLR, arXiv,
  Zenodo, SfN abstracts, OpenAI Blog, *Chronicle of Higher Education*,
  *Linux Journal*, CogSci proceedings).
- 10: pre-1960 without a candidate (`Land95` *Deutsches Wochenschach* 1895,
  `MullPilz00` Z. f. Psychologie 1900, `Skag25`, `Gate17`).
- 62: "other". Some venues are not in Crossref, and some entries are chapters
  typed as articles (`Tulv95` "The Cognitive Neurosciences", `PribEtal74`,
  `LeCuBeng95`).
- 5: EPMC has a record but Crossref has no plausible one.
- 4: no journal field.

### 1h. Cross-cutting findings that explain why earlier batches missed these

1. **The year-conflict flag blocks correction proposals.**
   `correction_proposals.field_proposal` allows only the target field's issue
   strings, so any entry that also carries the year-conflict flag can never get
   a proposal. The same applies to the `publisher` flag and to rivals, because
   `reassess` must reach `metadata_verified`.
2. **The existing machinery yields little on T3.** Run read-only on T3 (513), it
   produced only 25 proposals (22 author, 2 title, 1 journal), and several are
   already audit-excluded:
   - `HopkEtal12`/`CahiEtal96` would downgrade full names to initials:
     "Proposal discards existing given-name information".
   - `KragEtal19`: "Family/given boundary for Lisa Feldman Barrett...".

   Only 17 of the 1,945 appear in any `*-audit-exclusions.json`. The rest fail
   the preconditions.
3. **The APA DOI twin hides PubMed evidence.** PubMed stores the doubled-slash
   APA DOI (ESummary for `CleeMcCl91` and `CraiEtal96`: `10.1037//0096-3445...`).
   The Crossref best candidate is often the single-slash twin, so the exact-DOI
   Europe PMC query misses. There are 207 APA-DOI entries without EPMC evidence
   (84 with a twin already retrieved, 123 without).
4. **Pre-2000 psychology coverage in PubMed is partial.** Coordinate search
   (`volume[vi] AND firstpage[pg] AND year[dp] AND surname[au]`) found 3 of 8:
   - Found: `CleeMcCl91` PMID 1836490, `CraiEtal96` 8683192, `Game62` 13896567.
   - Not found: `ElliHenn80` (Br J Psychol), `MarmEtal78` (Am J Psychol),
     `RadeEtal99` (Ergonomics), `HockMurd87` (Psych Rev 1987), `Gree86a`
     (JEP:LMC 1986).

## 2. Resolution routes per class

Evidence rules keep the accuracy contract: similarity never authorizes, no ±1-year
tolerance, no generic stripping of "The" or sections, and no DOI substitution.

### (a) Legitimate matcher improvements (resolver revision 28, offline reassessment)

- **R1 "Crossref states its own earliest date".** Treat the year as
  single-valued only when all of the following hold:
  - `published-print` has one year Y;
  - `issued` (Crossref's earliest date by definition) has the same Y;
  - Y equals the cited year;
  - every other date is `published-online` > Y;
  - volume and pages both match.

  This is not a tolerance: Crossref itself says the work was first published
  in Y, and the later online date is a backfile deposit. Every other shape stays
  blocked. That includes online-first (`LindEtal21`), which keeps using the
  existing PubMed or Cambridge print-year corroboration. It also includes
  online = cited with a later print year (24), which is a user policy decision:
  change to the print year, or accept the online year. The rule needs a doc
  change, because docs/verification.md currently says "Direct Crossref
  publication dates must collapse to a single year".
  Direct yield: ~40 entries. It also unblocks correction proposals for about
  150 more in T3–T6.
- **R2 "coordinate-disjoint rivals".** A rival stops blocking only when:
  - it is a different type (book-chapter or posted-content) while the citation
    is @article and the selected record fully matches journal, volume and pages;
  - or it contradicts the citation on year, volume, or first page (not a
    missing or partial field). This covers reprints like `Este50`.
  - APA twins count as one work only when both records are fully clean and
    have identical title, authors, journal, volume, issue, pages and year. Any
    update or relation on either twin keeps the block (`Pike84`,
    `YoneJaco96a`). No DOI gets written into the entry.

  Same-journal duplicate registrations (`Knut07`) stay held.
  Yield: ~70–75 entries.
- **R3 enumerated journal variants.** Extend the exact alias table only with
  pairs documented from NLM Catalog or ISSN Portal records, in the same audited
  style as existing entries. Initial list: "american journal of psychology" →
  "the american journal of psychology"; the bilingual Canadian titles; "lancet"
  → "the lancet"; "annals of statistics" → "the annals of statistics"; QJEP →
  "... section a" / "... a", but only for years in the section's range. Yield:
  ~4 direct, and it unblocks ~40 multi-field entries.
- **R4 publisher history, for T2 (123).** Two options for the user:
  - (i) A dated publisher-history table built from NLM Catalog publisher
    statements. Example: *Nature Neuroscience* "Nature America / Nature Pub.
    Group" for years ≤2015, now Springer Nature. Accept only when the citation
    publisher matches the history for the cited year and the journal ISSN
    matches. That is about 10–15 table rows covering 100+ entries.
  - (ii) A policy decision to drop the non-standard `publisher` field from
    @article entries. That is a bibliography edit and needs explicit consent.
- **R5 citation LaTeX symbols.** Map an explicit whitelist
  (`$\alpha$`–`$\omega$`, `$\times$`, `\textregistered`, `\texttrademark`) to
  their Unicode characters. For source JATS `<sub>`/`<sup>`, compare only
  against a second plain-text source (PubMed), never by stripping. This affects
  about 25 entries.

### (b) Source-backed citation corrections (frozen proposal batches, `documentary_edits.py` pattern)

After R1–R3 land, extend `correction_proposals` with these classes. Each one
requires Crossref and a DOI-linked or coordinate-bound PubMed record to agree on
the replacement value, with every other field matching.

| Class | Size estimate | Rule |
|-|-|-|
| JEP:General → "Journal of Experimental Psychology" for ≤1974 | ~50 | Existing `journal_history_proposal`; blocked today by year and rival flags |
| "Psychological Science" → "Psychonomic Science" (1964–72) | ~12 | New dated history row, same pattern as JEP |
| Typo'd journals (Behavioural, Physiological Reviews, Psychophysiology, Acoustical...) | ~20 | `field_proposal('journal')` once unblocked |
| Surname typos and missing accents | ~170 | Adopt the source spelling only when Crossref and PubMed agree letter-for-letter, including diacritics; otherwise hold |
| Citation has fewer initials than the source | ~134 | Add the initials/names both sources give. Never drop citation information (the existing audit rule) |
| End-page errors, `.eN` suffixes, article numbers mis-stored as page ranges, DOI strings in pages/volume | ~120 | Pagination proposals; the DOI-in-field cases (`WeisEtal16`, `Finn21`) need a new "misplaced identifier" class, with the DOI verified by Crossref lookup |
| Title typos and punctuation | ~230 | `field_proposal('title')` with `source_title()` guards (numbered headings, joined words, markup already raise) |
| Missing subtitle | ~40 | Adopt the full source title when both sources agree |

Expected yield after R1–R3 unblock (estimate): 45–60% of T3 (230–310 entries)
and 25–35% of T6 (170–230). Every batch gets a personal spot check against a
publisher page or PDF before staging.

### (c) New sources

1. **Twin-aware Europe PMC.** When Crossref returned an APA twin, query EPMC with
   both registered DOIs. For the 123 APA entries without a retrieved twin, first
   fetch the doubled-slash DOI from Crossref. That confirms the twin exists; it
   is a registry lookup, not a guessed identifier, and still needs your policy
   sign-off. Cost: ≤10 EPMC batch requests plus ≤123 Crossref lookups.
2. **PubMed coordinate search (discovery) plus a "coordinate-bound PMID"
   identity rule.** The PMID is accepted as the secondary source only when:
   - the PubMed DOI equals the Crossref DOI or its twin; or, if PubMed has no DOI,
   - the ISSN matches Crossref's, and volume, first page, year, first-author
     surname and normalized title are identical;
   - and exactly one PMID results.

   Target: 909 entries with no EPMC evidence. The probe hit rate was 3 of 8, so
   an estimated 250–400 hits. Cost: about 900 ESearch requests (≈15 min at
   1 request/s) plus about 5 ESummary batches.
3. **Publisher landing-page `citation_*` meta tags** (reuse the publisher-title
   HTML/XML pilot transport). This mainly serves the "citation has more given
   names than the source" subtype (186 entries). An exact printed-byline match
   from the publisher page or PDF resolves it; PubMed initials cannot. Cost:
   ~300 requests, paced per host.
4. **Non-DOI venue adapters (Z, 44).** Sources:
   - proceedings.neurips.cc per-paper BibTeX;
   - jmlr.org and proceedings.mlr.press BibTeX;
   - the OpenReview API for TMLR;
   - DataCite for Zenodo (adapter already exists in `fallback_evidence`);
   - the arXiv route (already exists).

   Many of these are mistyped @article entries. The correct fix is an
   entry-type correction, after which they move to the proceedings/preprint
   group.
5. **Local PDF library (read-only).** Existing indexes cover this group:
   `.bibcheck/local-library/candidates.json` has title-page candidates for 129
   of the 1,945 keys, filename == key for 92, and `key-candidates.json` has 90.
   Use it for adjudication evidence only, since a PDF/OCR finding alone is not
   approval.
6. **JSTOR, PsycNET, OpenAlex, Semantic Scholar.**
   - JSTOR and PsycNET have no usable public metadata API, so they are unknown
     or unusable for automation.
   - OpenAlex and Semantic Scholar largely mirror Crossref and PubMed, so they
     are not independent. They should not count as a second source; at most
     they help discovery.

### (d) Human adjudication

- **Size (estimate).**
  - Z residue: ~110.
  - Author "citation more complete than every source" with no publisher/PDF
    byline: ~80–120.
  - Author count differs by ≥3: 52.
  - Wrong-candidate or preprint-title cases (`ScanEtal21`, `PetrPand94`,
    `KingEtal11` group author): ~60.
  - Crossref/PubMed conflicts (T4): ~40.
  - Pre-1960 and non-indexed journals (Am J Psych 1920s, Z. f. Psych.): ~60.
  - The remaining T5/T6 not reached by new sources: ~300–400.

  Total: **~750–950 entries (≈40–50%).**
- **What the review page should show per entry.**
  - A field-by-field grid: the citation vs each source (Crossref, PubMed, PMC
    JATS, publisher meta, PDF title page), with token-level diff highlighting,
    including diacritics and initials.
  - Every candidate DOI with type, venue, volume and pages, the twin, reprint
    or preprint relations, and any notice/update flags.
  - The local PDF first-page preview (the `.bibcheck/local-library/previews`
    already exist) and the page number where the byline or title appears.
  - The proposed correction, if any, with before/after.
  - Actions: accept the citation as-is (verified by document); apply the
    proposed correction; choose a different candidate; hold (the reason is
    required).
  - Each decision records the adjudicator's name, a timestamp, the evidence
    hashes, and the entry fingerprint. The result is a `human_verified` record,
    invalidated on edit.

  Batch by journal and decade so one reviewer can check many items against the
  same source volume.

## 3. Order of work, effort, network cost, pilots

| Step | Work | Network | Expected yield |
|-|-|-|-|
| 1 | R1 + R2 (+R3 aliases) as resolver 28, with tests, doc update, offline `auto-review` | 0 (R3 needs ~10 NLM lookups to document aliases) | ~115 verified with no edits |
| 2 | Re-run existing proposal generators on the newly unblocked entries (frozen batch) | 0 | Estimated 60–120 corrections |
| 3 | Twin-aware EPMC + PubMed coordinate search (discovery, then identity rule) | ~1,050 requests | PubMed evidence for 250–400 more entries |
| 4 | Extended correction classes (accents, surname typos, initials, pages, titles, JEP/Psychonomic history) | 0 (reuse step 3 evidence) | Estimated 300–450 |
| 5 | Publisher decision (R4 table or field drop) | ~15 | ~120 |
| 6 | Publisher meta, non-DOI adapters, entry-type fixes | ~350 | Estimated 100–150 |
| 7 | Human review UI and adjudication | 0 | The remainder, ~750–950 |

Overall estimate: **~50–60% resolvable by deterministic rules and two-source
corrections (≈1,000–1,150 entries); ≈40–50% need a named human (≈800–950).**
The uncertainty is mostly the PubMed hit rate (measured on 8 entries only) and
how many T6 entries clear after the cascade.

### Pilots (each ~20 entries; frozen key lists; fingerprint-asserted; repeat must make zero requests and zero writes)

- **P1 (R1, offline).**
  - Positives: `Zoll90`, `MuijReyn03`, `Gall00`, `Dobr70`, `MarsWatk01`,
    `StonDawe93`, `ShutEtal83`, `RadeEtal99`, `Shim95`, `ElliHenn80`,
    `JuanRabi85`, `MummEtal00`, `FoosEtal87`, `RabiSamb75`, `HamiSuth99`,
    `BurtBruc92`, `Salt93`, `MeyeRice81`, `DuchEtal98`, `AwadEtal91`.
  - Negative controls: `LindEtal21`, `BaleEtal21`, `GuoEtal20`, `StonEtal18`
    (cited 2018, Crossref 2008).
  - Success: 20/20 verify, 0 controls verify, the 60/60 benchmark is unchanged,
    and the full test suite passes.
- **P2 (R2, offline).**
  - Positives: 10 APA twins (`JacoEtal92`, `Gree86a`, `HockMurd87`, `John91`,
    ...), 5 chapter reprints (`Gros88`, `SchuEtal97`, `Rabi89`, `AndeEtal98a`,
    `Kuhn55`), 3 preprints (`HakiEtal20`, `Niv21`, `Rang19`), plus `Este50` and
    `Raic06`.
  - Negative controls: `Pike84`, `YoneJaco96a`, `Knut07`.
  - Success: all positives verify; all controls remain held.
- **P3 (publisher, R4-i).** 20 Nature Publishing Group / Psychonomic Society
  entries from T2 (e.g. `KurtEtal17`, `BuchEtal13`, `MostEtal17`). Success:
  every accepted pair cites an NLM Catalog publisher statement for the cited
  year, and there are 0 cross-journal matches.
- **P4 (corrections).** Five each of:
  - JEP anachronism: `Game62`, `HilgEtal53`, `HoroEtal64`, ...
  - Surname typo or accent: `CleeMcCl91`, `FourEtal19`, `GronEtal00`,
    `StopEtal07`, `ZhanEtal18b`.
  - End page: `CraiEtal96`, `ZhanEtal23`, ...
  - Title typo or punctuation: `BeamJone98`, `WangGuo19`, `KiEtal16`,
    `PosnEtal87`.

  Success: every proposal has Crossref + PubMed value agreement, is checked
  personally against a publisher page or PDF with 0 disagreements, and verifies
  after editing. Cite keys stay unchanged.
- **P5 (PubMed coordinate search).** 20 entries without EPMC evidence, drawn
  from JEP:LMC, Psych Review, J Neurosci, Am J Psych and Brain. Success:
  report the hit rate; 0 PMIDs accepted that fail the identity rule; a manual
  check of all hits.
- **P6 (human review UI).** 20 hard cases, e.g. `HopkEtal12`, `ScanEtal21`,
  `KingEtal11`, `Skag25`, `vandEtal11`, `LindEtal21`, `AharEtal01`. Success: a
  reviewer can decide each in ≤2 minutes, and the decision survives a snapshot
  restore.

## 4. Unknowns

- The PubMed hit rate is based on only 8 probes.
- It is unclear whether the user wants online-year citations changed to the
  print year (24 entries plus the key-name exceptions that would follow).
- The user has not chosen between the publisher-field policy options (R4-i
  vs R4-ii).
- It is unclear whether constructing an APA doubled-slash DOI for a Crossref
  existence check counts as "guessing identifiers" under current policy.
- The coverage of publisher `citation_*` meta for 1960–1990 articles is
  unknown.
