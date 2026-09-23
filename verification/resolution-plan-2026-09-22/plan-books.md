# Plan: 413 unresolved book-like entries (books, chapters, theses, reports)

Date: 2026-09-22. Planning only: no edits to `cdl.bib`, the cache, or tracked files.
Inputs were `group-books_chapters.json` (413 entries) and the latest `reviews` row
per key in `.bibcheck/verification.sqlite3`, opened read-only. I made 12 live
requests, listed in section 5.

Scratch artifacts, all in this scratchpad and all derived:
- `books-diag.json`: best candidates and issues for each entry.
- `books-classes2.json`: registry identity class for each entry.
- `books-coarse.json`: the primary class used below, one per entry.
- `books-localpdf.json`: local-PDF leads.
- `probe-results.json` and `probe2-results.json`: the live probe responses.
- `an*.py` and `show.py`: the scripts that produced them.

## 0. Composition

| Type | n |
|-|-|
| incollection | 191 |
| book | 158 |
| inbook | 44 |
| techreport | 10 |
| phdthesis | 7 |
| manual | 2 |
| mastersthesis | 1 |

Issue strings in the data:
- "No unambiguous, fully supported metadata match": 257 entries.
- "No unique, fully matching catalogue edition": 156 entries, all of them `book`.

Other observations:
- Only 2 entries have a DOI (Thor13 and one other book). None has an ISBN.
- 183 entries have pages, 212 have an editor and 270 have an address.
- No entry has any `external_evidence` attached.
- LOC catalogue results exist for 121 of the 158 books. The catalogue route is
  books-only: `assess_catalogue` raises "Catalogue route requires a book without
  a supplied DOI". Chapters, theses and reports were never catalogue-checked.

## 1. Diagnosis

### 1a. Code-level blockers (these stop a pass even when the identity is right)

These counts are over the best identity-matching Crossref candidate for each
entry, where the title matches and the first-author surname matches:

| Blocker string on the best candidate | Entries |
|-|-|
| `address: no deterministic verifier for this field` | 116 |
| `editor: no deterministic verifier for this field` | 97 |
| `pages: source supplies a field absent from the citation` | 41 |
| `chapter: no deterministic verifier for this field` | 29 |
| volume/number supplied by the source but absent from the citation | 19 / 18 |

Across all the title-matching chapter candidates, the Crossref chapter records
carried an `editor` array in only 2 of 339. A live probe shows that parent-book
records do carry editors:

- Probe: `api.crossref.org/works?filter=isbn:9780195134971,type:edited-book`.
- It returned "type":"edited-book", with editor "Donald T." Stuss and
  "Robert T." Knight.
- The chapter ISBN links chapter to book deterministically.

So an editor verifier is feasible. It would go through the parent-book record,
reached by ISBN or DOI, not through the chapter record.

`inbook` semantics: in 35 of the 44 inbook entries, the `title` field holds the
*book* title and the `chapter` field holds the chapter title (examples: Bord08,
HallGree08, ScotEtal07, McKeBuzs16, Tulv07). Discovery searched by the book
title, so a chapter identity was never looked for.

### 1b. Loose title matches are not identity

A "title match" is often an unrelated work with the same title:

| Key | Cited | Crossref best candidate |
|-|-|-|
| Kaha17 | Kahana, "Memory search" | "Memory Search", *Models of Human Memory*, Elsevier, 1970, author Shiffrin |
| Tulv72 | "Episodic and semantic memory", 1972 | a 2017 chapter by Rosenbaum et al. |

I therefore require the first-author surname to match as well before calling a
candidate an identity. Candidates that have no authors ("noauth", 38 chapters)
are treated as having no identity.

### 1c. Taxonomy: full population

Every entry is classified once. Counts are exact, from `books-coarse.json`.

| Class | n | What blocks it (observed) | Examples |
|-|-|-|-|
| **C-NONE**: chapter with no chapter-level registry record | 128 | Mostly pre-DOI edited volumes. By decade: 1970s 36, 1980s 19, 1990s 33, 2000s 48. Top publishers are Erlbaum (34), Academic Press (15) and MIT (11). A live OpenAlex probe for Wick72 "Characteristics of word encoding" (1972) returned count 0. The LOC volume records I checked (MeltMart72, TulvDona72, GorfHoff87) have **no 505 contents note**, so the catalogue cannot give chapter titles or pages. | Wick72, Unde72a, Brin65, OhrtGron99, Jord86, WebeMurd89 |
| **C-INBOOK**: chapter title stored in `chapter` | 35 | The search used the book title. Some probably have chapter DOIs (for example, Springer's "The basal ganglia VIII"). | Bord08, BoraEtal05, WardEtal09, HallGree08 |
| **C-REG-structural**: chapter identity OK, only blocked by editor/address/absent pages | 4 | Blocked only by the missing verifiers. | Tulv02b, HoyeVerh06, Hock08 (pages 417-444 absent), MoscWino02 |
| **C-REG-variant**: identity OK; publisher or container string differs | 21 | See the list below this table. | KansEtal15, AlyTurk17, Engl09, RehmNaus90, Mont98, SzpuTulv11, Mann24, Baum08 |
| **C-REG-date/type**: identity-like, but year, volume or type differs | 42 | The registry record is a reissue, an anthology reprint or a serial volume. See the list below this table. | BaddHitc77, Mins75, Hint76, Post61, HealPark01 |
| **C-REG-byline/pages**: identity-like, but byline or pages differ | 5 | Needs source inspection; may be citation errors. | NybeCabe00, Rugg00, RuggAlla00, Shif70b, NivMont09 |
| **B-LOC-parse byline**: LOC record found, responsibility grammar rejects it | 35 | See the list below this table. | Fust05, Kaha12, Badd90, Buzs06, Hebb49, Guth35, RiekEtal97, Chos05 |
| **B-LOC-parse date**: LOC date form rejected | 22 | Bracketed supplied dates, and 008 type 'r' reissues. | BishEtal75, Kint70, UndeShul60, Keme72, Penf75, Munn50, Penf58b, Whor56 |
| **B-LOC-parse imprint**: 264/dual/distributor/place grammar | 23 | Rejections: "This route requires one legacy publication statement" (RDA 264, as in Carr16 and Huth13); "Missing or ambiguous MARC field 260b" (dual imprints such as Clarendon ; Oxford University Press, in Tulv83, Paiv86 and OKeeNade78); "Publisher role is uncertain" (distributor clause, Murd74). | Tulv83, Paiv86, OKeeNade78, Ande76, Carr16, Huth13, Murd74 |
| **B-LOC-parse corporate**: 110/111/710/711/7xx | 7 | Edited volumes and conference volumes. | TulvDona72, MeltMart72, GorfHoff87, LincNati81 |
| **B-LOC-fieldmismatch**: a parsed edition differs only in publisher, place or edition | 17 | Often a **citation defect**. See the list below this table. | Jens80, RoseRosn91, Klin05, Howe97, Zar10, Unde83 |
| **B-LOC-identitymismatch**: parsed records differ in title, author, year or volume | 17 | Wrong edition or a citation typo. Free00 cites "How brain make up their minds"; the book title is "brains". Others include Mart98, TuftGrav83 and Prib91. | Free00, Mart98, BendPier01 |
| **B-NONE**: no LOC hit and no registry identity | 30 | Mostly **citation defects or wrong entry types**. See the list below this table. | BirdEtal09, Hull43, Vapn95, Kani79, Wern84, Plat99 |
| **B-REG-only**: registry identity is a reissue or archival record | 7 | The registry record is a later or archival publisher's; it cannot supply the original imprint. | Mill96, yCaj91, DeliEtal00, Ship46, Rank18, DaviHink97, Nune95 |
| **T-THESIS** | 8 | No catalogue route exists. OpenAlex found Nola11 as type "article" with no DOI, so it is weak. Mann06 and Mann11 are the user's own theses. | deBr24, Nota17, Nola11, Mann11, Mann06, Poly05, Weic96, Ekst04 |
| **T-REPORT/MANUAL** | 12 | See the list below this table. | CannEtal16, CoghStuf13, vanREtal14, Shan20, RCor12, Stan13, BradLang99, RussJenk54, vond81, Alva02, WolzEtal88, AdamEtal10 |
| **Total** | **413** | | |

Details for the larger classes:

- **C-REG-variant** differences observed:
  - Springer: "Springer International Publishing" and "Springer US" against a cited "Springer" or "Plenum Press".
  - A registry concatenation bug: "Oxford University PressNew York, NY" (Mont98).
  - Container is the multi-volume set, not the cited volume: Baum08 cites *Cognitive Psychology of Memory*; the registry has *Learning and Memory: A Comprehensive Reference*.
  - Container is a "Two Volume Pack" (Mann24).
  - Series versus volume title (KansEtal15 is in *Current Topics in Behavioral Neurosciences*).
- **C-REG-date/type** records observed:
  - BaddHitc77: a Routledge 2022 reissue with the same pages, 647-667.
  - Mins75: MIT *Mind Design II*, 1997, pages 111-142, and an Elsevier 1988 anthology.
  - Hint76: an Elsevier serial DOI for *Psychology of Learning and Motivation*.
  - Post61: an APA record with year None and pages 152-196, against the cited 109-118.
  - HealPark01: an APA record with year None.
- **B-LOC-parse byline** failures observed:
  - A full given name in 245c against initials in the heading: Kahana, "Michael Jacob Kahana".
  - An accented name: Fust05, "Joaquín M. Fuster".
  - A missing 245c: Hebb49, Guth35, Yate66.
  - "[et al.]" (RiekEtal97, Chos05), which should stay unresolved.
  - "edited by" (HorcDhil04).
  - A LOC cataloguing typo: Jame90's only record transcribes "by William Jones".
- **B-LOC-fieldmismatch** examples:
  - Jens80: cited publisher "{ERIC}", LOC 260 has "Free Press".
  - RoseRosn91: the only LOC record is "2nd ed", and the citation has no edition.
- **B-NONE** defects observed:
  - Title typos: "Nature language processing" (should be *Natural*), "Principals of behavior", "Grundriss der psychiatrie" dated 1984 (the evidence points to 1894).
  - Author typos: "Vapnick", "Kanisza", "Piepenrbrock".
  - Edition or volume text in the title: GelmEtal13 ", Third edition", Cohe88 "2nd ed", McGeIrio52, McClEtal86, RumeEtal86a.
  - Wrong entry type:
    - Kele99 is a diploma thesis.
    - Plat99 is a chapter in an edited volume.
    - TellPalm98 is an encyclopedia entry.
    - Rayp68 is a journal supplement.
    - BaayEtal95 is a database.
  - Corporate authors (Amer23a/b).
  - Thor13 has an APA DOI, so the catalogue was never tried.
- **T-REPORT/MANUAL** contents:
  - 4 Python PEPs.
  - 2 corporate software manuals (RCor12, Stan13).
  - 6 institutional reports, some with no institution (BradLang99, RussJenk54, vond81).

### 1d. Stratified manual sample (about 100 entries inspected)

I read about 100 entries in full, with their best candidates or LOC MARC:
- all 45 LOC-unparseable books;
- all 58 books in the no-hit or mismatch lists;
- 15 detailed chapter dumps;
- a random 25 of the chapters with no identity;
- all 20 theses and reports.

What the sample showed:
- **Citation defects are common and visible.** In the B-NONE list, at least 17 of 30 have a typo, edition text in the title, a wrong entry type or a corporate author. Further citation-side problems in other classes:
  - Kaha17 cites *Learning and Memory: A Comprehensive Reference* with the publisher "Oxford University Press". The Hock08 and Baum08 records for that reference work say Elsevier.
  - Jens80's publisher is "ERIC".
  - ChenGall84 has the typo "peometric".
  - Tulv70 has pages "7--9".
  - SilbEtal01 is a *Proceedings* paper typed as incollection.
- **Reissues dominate registry candidates for old works.** Examples:
  - Paiv71: Psychology Press 2013.
  - Koff35: Routledge 2013.
  - BaddHitc77: Routledge 2022.
  - EfroTibs93: "Springer US" for Chapman & Hall 1993.
  - Wear16: "Palgrave Macmillan UK" for a cited "Springer".
  - LOC also returns reissues: Robi32 only matched a Hafner 1964 record, Whor56 only a 2012 record (008 r20121956), and DudaEtal01 only the 2004 MATLAB companion.
- **Real edition and printing ambiguity.** For Titc16, Internet Archive returns *A beginner's psychology*, Macmillan, dated **1915**, with a 1928 printing, but the citation says 1916. For Tulv83, Open Library returns a 1985 Clarendon paperback, while HathiTrust has 1983 with four ISBNs, including the pbk.

## 2. Routes, in priority order, with acceptance rules

General rules, which apply to every route:
- Every approval is `metadata_verified` from a deterministic comparison with retained raw evidence, or `human_verified` with a named reviewer, source and fingerprint.
- An edition, reprint, reissue or translation never substitutes for the cited one.
- A review of a book never substitutes for the book.
- A work-level record (such as an Open Library *work*) never supplies edition fields.
- LLM, OCR and PDF text extraction only produce leads. A visual check of the source page or a deterministic source comparison must follow.

### R0: Verifier completeness (code, offline first). Targets C-REG and part of the books. Est. 25 to 35 entries.

1. **Editor verifier.** Accept `editor` only when one of two sources confirms the full ordered editor list:
   - (a) a Crossref parent record of type `edited-book` or `book`, reached from the chapter's own ISBN (`filter=isbn:…,type:edited-book`, with exactly 1 result) or from a DOI-prefix relation the chapter record states. It must have the same title as `booktitle`, and the same year.
   - (b) a LOC MARC record for the parent volume, whose 245$c "edited by …" statement **and** 700 headings with $e editor agree.

   The same name rules as authors apply: initials agree with given names, and every surname and the order must match. No partial lists are accepted.
2. **Address verifier.** Accept the first place when either:
   - it equals the edition's LOC 260/264$a place, using the existing state-code rule; or
   - it equals Crossref `publisher-location` on the *same* edition record, and that record's year and publisher also match.

   A reissue's location never counts.
3. **Chapter-number verifier.** Accept only from a publisher chapter record that states the number (for example, OUP DOI `.003.0011` together with a printed "Chapter 11"), or from a visual source. Otherwise route it to human review. Do not infer the number from the DOI suffix alone.
4. **"Source supplies pages absent from citation."** Do not relax this. Handle it with a correction proposal that adds the pages (Hock08 417-444), frozen, and checked by the ordinary verifier after the edit.
5. **inbook semantics.** When `chapter` is non-numeric, search and compare it as the chapter title against Crossref `book-chapter`, and compare `title` against `container-title`. Alternatively, propose inbook to incollection conversions as a frozen batch. That second option is a user decision, because it changes the entry type.

**Acceptance for C-REG after R0:** the Crossref chapter record's title, full ordered byline, container, pages and year all match. Publisher must match through the documented equivalence list (next item) or an edition-bound binding (the `book_editions.json` pattern). The editor and address must pass rules 1 and 2.

### R1: Frozen, source-backed citation corrections (`documentary_edits.py` pattern). Est. 60 to 90 entries need at least one.

Candidates:
- the typos in B-NONE and B-LOC-identitymismatch;
- edition text moved out of the title into `edition`;
- missing `edition` where the only matching LOC record states one (RoseRosn91 "2nd ed", Klin05, Howe97, Zar10);
- wrong publisher (Jens80, Kaha17);
- series or volume container corrections (Hint76, Baum08, KansEtal15);
- wrong entry types (Kele99, Plat99, TellPalm98, Rayp68, BaayEtal95, SilbEtal01);
- missing pages taken from a matching chapter record.

**Evidence rule:** each changed field needs two independent agreeing sources for the *same edition*, or one source plus a visually inspected title page or copyright page. Accepted sources:
- a LOC MARC record plus the chapter or book DOI record;
- a LOC record plus a local PDF, or a HathiTrust or Internet Archive page image.

Keep every original key; the existing key-exception mechanism covers year and author changes. After each edit, the ordinary pipeline must then verify the new fingerprint. A correction is not itself an approval.

### R2: LOC MARC grammar extensions, offline against cached MARC. Targets 87 B-LOC-parse. Est. 30 to 50 entries.

Each extension is narrow, has tests, and has a negative control from real records:

| Extension | Rule | Examples | Negative control |
|-|-|-|-|
| a. Bracketed or copyright date | Accept "[1970]" or "c1970" only when 008/06='s' and 008/07-10 equals the bracketed year. 008 'r' (reissue) stays rejected. | Kint70, BishEtal75 | BishEtal75 has 008 1974 against a transcribed [1975], so it stays unresolved |
| b. RDA 264 | Accept exactly one 264 with ind2=1 as the publication statement. Ignore 264 _4 (copyright). | Carr16, Huth13 | |
| c. Dual imprints | For "Oxford : Clarendon Press ; New York : Oxford University Press", accept a cited publisher/place pair that equals one transcribed publisher with *its own* place. Never mix a place from one with a publisher from the other. | Tulv83, OKeeNade78, Paiv86 | |
| d. Distributor clauses | Strip "distributed by …" only when it is a separate clause after ";". The cited publisher must equal the named publisher, not the distributor. | Murd74, Ande76 | |
| e. Absent 245$c | Allow a single 100 heading as the byline when there is exactly one author, 245$c is absent, and 008 is a single-year record. | Hebb49, Guth35, Yate66 | |
| f. Full-name statements | "Michael Jacob Kahana" confirms "M J Kahana" (initials agree). | Kaha12 | |
| g. Edited volumes | "edited by" plus 700 $e editor confirms `editor` for editor-only books. This is also the parent-volume route in R3. | HorcDhil04, TulvDona72 | |

Accents: extension f must keep the accent behaviour. Fust05's "Joaquín M. Fuster" failed, and the cause is unknown (it may be a diacritic or the second given name). Diagnose it before extending.

These extensions keep the following unresolved:
- "et al." (RiekEtal97, Chos05);
- Jame90, whose LOC record reads "William Jones". A human must compare the title page.

**Run:** offline reassessment of the cached search XML; a new catalogue policy 7 re-opens only unresolved entries.

**Success:** no previously verified book changes. Every new positive gets personal spot-checks against the MARC and, where available, a title-page image.

### R3: Chapter verification when catalogues only cover the volume. Targets C-NONE, C-INBOOK and the C-REG reissues. Est. 30 to 60 automatic.

A chapter is `metadata_verified` only when **both** layers pass:

- **Volume layer** (booktitle, editors, publisher, place, year, edition, volume or series): one LOC MARC edition record of the parent volume that passes the R2 rules, including the editor rule in R0.1(b). Search it by booktitle plus first editor surname (dc.title and dc.author), using the existing year refinement.
- **Chapter layer** (chapter title, full ordered chapter authors, first and last page), from one of:
  - (i) a Crossref chapter record bound to *that same edition*: same ISBN, or DOI prefix of the same edition, and same year. A reissue DOI such as 10.4324/9781003309734 (2022) is **not** the 1977 edition, even when its pages are identical.
  - (ii) a visually inspected page image of the chapter's first page with the printed running head or folio, plus the volume's table of contents. Sources for the image:
    - a local PDF (13 filename matches in this group; see `books-localpdf.json`);
    - a HathiTrust full view (public-domain volumes);
    - a publisher TOC page.
  - (iii) HathiTrust full-text "search only" hit pages. Their feasibility is **unknown and untested**. A probe returned only "Limited (search-only)" items for Tulv83, and page-number search results have not been tried. Pilot it before relying on it.

  Pages must match exactly. A printed folio is required for the last page; extracted text alone is not enough.

Other options:
- **Publisher binding for archival registries** (the Plenum → "Springer US", Academic Press → Elsevier, Erlbaum → Routledge/Psychology Press reprints pattern). This follows `book_editions.json`, one binding per edition. Each binding needs visually inspected original front matter, the LOC record and the archival DOI. The live Springer book probe confirms the problem: it gives publisher "Springer US" and publisher-location "Boston, MA" for a 1990 book cited as Plenum Press, New York.
- **Serial-volume chapters** (Hint76, Post69, Shif75, Epst72, Lash50): the verifier would compare `booktitle` against the series title plus the volume. This needs a correction proposal that adds `volume` and fixes `booktitle`, then an ordinary verification.

### R4: Structured non-catalogue sources for reports, theses and manuals.

- **PEPs** (CannEtal16, CoghStuf13, vanREtal14, Shan20): `https://peps.python.org/api/peps.json`, live-verified. For PEP 484 it gives "authors": "Guido van Rossum, Jukka Lehtosalo, Łukasz Langa" and "created": "29-Sep-2014". A small deterministic route could compare the number, title, ordered authors, created year and institution="Python Software Foundation" (the institution needs a documented rule). Est. 4 automatic, possibly after corrections. Shan20 is typed "Draft PEP"; check its status field.
- **Theses:** university repository landing pages (DataCite or Handle records where present), or ProQuest (subscription access, **unknown**). The acceptance rule is the repository record's title, author, degree, institution and year, plus the thesis title page from a PDF. Mann06 and Mann11 are the user's own theses, so the user can adjudicate them quickly. Weic96 cites *Dissertation Abstracts International* 57(1-B):757, which needs the DAI record. deBr24's school field "Migration-université en cours d'affectation" is a HAL artifact and needs correction to the Université de Paris / Faculté des sciences (verify at the source).
- **Manuals and corporate works** (RCor12, Stan13, Amer23a/b, BaayEtal95, LincNati81): these are version-specific. Human adjudication against the versioned document, unless a registry DOI exists. The CELEX LDC catalogue ID is LDC96L14, which must be verified at the source.

### R5: Human adjudication (the remainder)

The packet for each entry contains:
- the cited fields;
- every candidate record (LOC MARC, Crossref, local PDF page renders);
- the specific conflict;
- proposed decisions: approve as cited, correct, or mark the edition.

The decision is recorded with `approve`: reviewer, source, notes and the exact fingerprint. Priority goes to entries where the machine evidence is complete but a policy forbids automation, such as:
- Jame90's LOC typo;
- the Titc16 1915/1916 printing question;
- Luca83, where LOC gives c1981 and the citation says 1983;
- the "et al." records.

## 3. Order, pilots and success criteria

| Step | Work | Network | Pilot | Success criteria |
|-|-|-|-|-|
| 1 | R0 editor/address/inbook verifiers, with tests | about 25 Crossref parent lookups | the 25 C-REG structural + variant entries | ≥15 verify. Negative controls BaddHitc77 (reissue), Kaha17 (unrelated title match), Hint76 (serial) and Mins75 (anthology) stay unresolved. Zero change to prior approvals. Repeat makes zero requests and zero writes. Full suite plus benchmark pass. |
| 2 | R2 grammar extensions a–g | none (cached MARC) | all 87 B-LOC-parse | ≥30 verify. Every positive spot-checked against the MARC. The controls listed in R2 stay unresolved. |
| 3 | R1 correction batch 1 | a few LOC searches for the corrected titles | about 20 obvious typos, edition-in-title and wrong-type entries | every changed field has 2 sources or a visual. The staged diff touches only the listed lines. Post-edit, ≥70% verify through normal routes. |
| 4 | R3 chapter pilot | LOC volume searches (3.1 s pacing), 10–15 | 10 chapters with local PDFs, plus 10 Erlbaum or Academic Press chapters without them | measures the yield of the volume layer and the chapter layer separately; zero reissue acceptances |
| 5 | R4 PEP route | 1 JSON | 4 PEPs | 4 verify, or explicit corrections |
| 6 | R5 human packet pilot | none | 10 mixed entries | record the reviewer minutes per entry to size the remaining human load |
| 7 | Scale steps 1–4 to their classes, then R5 on the remainder | | | |

Relative effort:
- Steps 1–2 are code-heavy but mostly offline: the highest yield per request.
- Step 3 needs careful manual source work, about 10–15 minutes per entry. This is an estimate.
- Step 4 is the costliest per entry and the hardest to automate.

## 4. Expected automatic versus human share (estimates, not measurements)

These ranges come from the class counts plus the defect rates in the sample. The chapter yield is the least certain, because no chapter-layer source for pre-DOI volumes has been proven yet.

| Class | n | Automatic (possibly after an R1 correction) | Human |
|-|-|-|-|
| C-REG (all four) | 72 | 35–50 | 22–37 |
| C-NONE + C-INBOOK | 163 | 35–70 | 93–128 |
| B-LOC-parse | 87 | 35–55 | 32–52 |
| B-LOC-mismatch | 34 | 15–25 | 9–19 |
| B-NONE + B-REG-only | 37 | 12–20 | 17–25 |
| Theses/reports/manuals | 20 | 4–6 | 14–16 |
| **Total** | **413** | **about 135–225 (33–55%)** | **about 190–280 (45–67%)** |

## 5. Live requests made (12, paced at 3.2 s or more)

1. Open Library `search.json` for Tulving's *Elements of episodic memory*: 200. It returned one work, OL5901283W, with only one edition (1985 Clarendon pbk, LCCN 82008241). **So Open Library work records conflate editions**; use it for leads only.
2. Google Books volumes: **HTTP 429** on the first request. Availability from this host is unknown and currently not usable.
3. Crossref OUP edited-book 10.1093/acprof:oso/9780195134971.001.0001: 200, with editors present.
4. Crossref Springer book 10.1007/978-1-4613-0649-8: 200. It gives "Springer US" and "Boston, MA" for the 1990 Plenum volume.
5. HathiTrust brief API, lccn 82008241: 200. It returned 1983, OCLCs 8552850 and 11370196, and items rights "ic", "Limited (search-only)".
6. OpenAlex, thesis title: 200. Nola11 was found as type "article", with no DOI.
7. OpenAlex, 1972 chapter "Characteristics of word encoding": count 0.
8. `peps.python.org/api/peps.json`: 200, structured authors and created date.
9. WorldCat `search.worldcat.org`: **HTTP 429**. It is not usable without an OCLC API key, and the key is not configured (unknown whether the user has one).
10. Crossref `filter=isbn:9780195134971,type:edited-book`: exactly 1 result, the parent with editors.
11. Open Library `api/books?bibkeys=LCCN:82008241`: **404**.
12. Internet Archive advancedsearch, Titchener: 200. It returned 10 scans, with Macmillan dates 1915, 1923 and 1928.

## 6. Open questions for the user

1. Convert the 35 inbook entries whose chapter title sits in `chapter` to incollection, or teach the verifier inbook semantics?
2. Are archival-publisher bindings acceptable, one inspected binding per edition? Examples are Plenum → Springer US and Academic Press serials → Elsevier.
3. Is ProQuest, WorldCat or Google Books API access available, via an institutional key or Dartmouth library proxy? Unknown.
4. Should the user's own theses (Mann06, Mann11) and the other lab-local documents be handled as direct human adjudications?
