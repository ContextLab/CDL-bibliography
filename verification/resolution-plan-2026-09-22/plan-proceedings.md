# Plan: proceedings, preprints, misc (158 unresolved entries)

Planning only, 2026-09-22. No edits were made to `cdl.bib`, the main cache, or any tracked file.
The main cache was opened read-only (`sqlite3 ...?mode=ro`) to read each entry's latest review.
There were 12 live requests, spaced about 2 s apart (results below).

Supporting scratch files, all in this scratchpad:
- `proc-taxonomy.json`: class to keys (all 158 keys, no duplicates, checked by script).
- `proc-best.txt`: best cached candidate per entry, with its residual issues.
- `p*.json/html/bib`: raw probe bodies.

## 0. Grounding: what actually blocked these entries

The group file gives entry types as follows: inproceedings 82, misc 44, conference 20, article 12.
Its issue text is "No unambiguous, fully supported metadata match" for 146 entries. The rest are
preprint or arXiv holds (9) and external-evidence holds (3).

Blockers read from the cache (best candidate per entry, `bibcheck/verification.py:compare_record`):

- **`booktitle` mismatch: 41 of the 49 Crossref-registered proceedings.** The booktitle uses
  plain `normalized()`. Unlike `journal` (`normalize_journal`, enumerated aliases at
  verification.py:916-958), it has **no alias mechanism**. The house style uses generic names,
  for example `{IEEE} Conference on Acoustics, Speech, and Signal Processing`. Crossref uses
  dated containers, for example `2013 IEEE International Conference on Acoustics, Speech and
  Signal Processing`.
- **The `@conference` type is unsupported.** `expected` at verification.py:1197-1203 has no
  `conference` key, so all 20 `@conference` entries fail as "publication type/version is
  unsupported". `proceedings-record-2026-09-14.md` already records this for VaswEtal17.
- **Some fields have no verifier** (verification.py:1263-1282): `organization` (10),
  `address` (6), `editor` (4) and `howpublished` (all URL misc entries). Each one alone blocks
  an entry. Examples: WangEtal10b has 0 other issues and ChenEtal22 has 0 other issues, yet
  both are unresolved for address/editor alone. CoppEtal17 is blocked by organization alone.
- **Non-Crossref authorities have no route.** NeurIPS before 2019 has no DOIs, and neither do
  PMLR, ACL Anthology pre-DOI papers, CogSci, abstracts, software, web pages and patents.
  Crossref title search then returns unrelated works: SfN abstracts matched PsycEXTRA,
  Frontiers or bioRxiv items, and "Llama 3" matched a textile dictionary.
- **DataCite is evidence but not approval** (`fallback_evidence` docstring, verification.py:1347).
  FitzEtal25's DataCite record has 0 comparator issues and is still unresolved.
- **Preprint results are stale.** All 6 bioRxiv entries carry `preprint_review.policy = "1"`,
  but `PREPRINT_POLICY = '2'` (preprint_review.py:20). Reassess them from the cache before
  doing any new work.

### Substantive discrepancies already visible (these are corrections, not route work)

| Key | Citation | Source (cached Crossref) | Note |
|-|-|-|-|
| HaonEtal16 | Y Haonan, W Jiang, H Zhiheng, Y Yi, X Wei | Haonan Yu, Jiang Wang, Zhiheng Huang, Yi Yang, Wei Xu | Given and family names are swapped in the citation |
| DengEtal09 | pages 710--719 | 248-255 (10.1109/cvpr.2009.5206848) | Pages wrong |
| YingEtal92 | 1992, vol 2, 732--735 | DOI icassp.1993.319416, date 1993, "732-735 vol.2" | Could be ICASSP-92 or ICASSP-93. Unknown; needs the IEEE record or a PDF |
| RosePaul90, Kais90, HuggEtal06, MakaEtal06 | year | Crossref has conflicting dates | Choose the proceedings year; do not take the online year |
| AndeEtal16 | 1242--1251 | Crossref pages differ | Check the IEEE record |
| WolfEtal20 | no booktitle; author count | EMNLP 2020 Demos, 10.18653/v1/2020.emnlp-demos.6 | Booktitle missing; byline count differs |
| RagaWill18 | 2 authors | SciPy 10.25080/majora-4af1f417-011, author count differs | Byline conflict; the source may list the Jupyter team |
| KluyEtal16 | IOS Press pp 87--90 | wrong chapter found | Needs DOI discovery (exact DOI unknown) |
| JianEtal24 | `D d l Casas` | Diego de las Casas | The citation parses "de las" as initials. Correct to `D {de las Casas}` |
| BetzEtal19 | F Z Esfahlani | bioRxiv partition "Zamani Esfahlani" | Probable surname error. Confirm with the version HTML and PDF |
| PolyEtal06 | 5 authors incl. N W Morton | PsycEXTRA 10.1037/e527352012-321 lists 4 (no Morton) | Byline conflict |
| WilsEmmo03 | Wilson and Emmorey | Crossref lists only M. Wilson | Registry incomplete; needs publisher or PubMed |
| FitzEtal25 | P C Fitzpatrick | DataCite/Zenodo "Paxton Fitzpatrick" (probe: Zenodo API) | Middle initial not in source |
| DeloEtal01 | "International Congress on Acoustics" | unknown | Suspected venue error (the paper is believed to be from the ICA 2001 workshop). Unverified; needs source |
| RangEtal14 | "Artificial Intellience and Statistics" | — | Typo in booktitle |
| AlvaEtal05 | "k-corr", "visualiztion" | PDF v2: "k-core", "visualization" | Title typos, confirmed in the saved audit |
| CordEtal02 | ISMRM venue with MRI journal vol/pages | Two different works mixed | See holds |

## 1. Taxonomy (158)

| Class | n | Keys | What blocked it |
|-|-|-|-|
| A1 Crossref proceedings, IEEE | 17 | CoppEtal17 DengEtal13 Subb13 NaroEtal11 KellEtal10a BlakEtal08 WangEtal10b AndeEtal16 XiaoEtal10 RosePaul90 Kais90 TardEtal08 HuggEtal06 MakaEtal06 YingEtal92 HaonEtal16 DengEtal09 | Booktitle, organization, address; the last 10 also have substantive issues |
| A2 Crossref proceedings, ACM | 14 | BleiLaff06 ScheEtal02 NguyEtal16b LiEtal16 TianEtal16b LiEtal17b TianEtal17 TianEtal18 LiEtal18 LiZhou18 TianEtal20b LiEtal20 CarvEtal22b StonEtal25 | Booktitle only for 11; ScheEtal02 type; StonEtal25 publisher+address; LiEtal18 given names |
| A3 Crossref, ACL-hosted DOI | 7 | WolfEtal20 PennEtal14 IyyeEtal15 ChenEtal22 Etha19 HewiMann19 BambEtal90 | 4 are @conference; booktitle; pages absent |
| A4 Crossref, ISCA | 3 | Kipp01 HalpEtal16 DolfWend98 | Booktitle; pages absent; title dash (Kipp01) |
| A5 Crossref, SciPy | 2 | RagaWill18 McKi10 | Byline/title; "related versions" |
| A6 Crossref, Springer LNCS chapters cited as @inproceedings | 2 | FiscMode03 dBakEtal08 | Type book-chapter vs inproceedings; dBakEtal08 surname `{d Baker}` |
| A7 Crossref, other | 3 | KluyEtal16 HeusMann18 AltmSchu02 | Wrong candidate; CCN pages; CogSci 2002 **2019 reprint** year |
| B1 NeurIPS (no DOI) | 6 | VaswEtal17 ParkPill12 RaoHowa08 LiuEtal18 LiuWang16 YangEtal13 | No route. YangEtal13 is a workshop paper with no proceedings volume |
| B2 PMLR (ICML/AISTATS) | 5 | AchiEtal17 JianLi16 FaraEtal18 ParkEtal24 RangEtal14 | No route |
| B3 ACL Anthology, no DOI | 1 | ZengEtal14 | No route; booktitle short form |
| B4 CogSci proceedings | 3 | ShafGood08 MozeEtal04 Plau95 | No route |
| B5 Other old proceedings | 6 | PellMoor00 BernClif94 BartEtal04c MuelShif06 DeloEtal01 MallEtal97 | No DOI found; DeloEtal01 venue suspect |
| C1 SfN abstracts | 20 | RamaEtal12a WatrEtal09 DerdEtal06 vanVEtal05 GratEtal11 KrauEtal12 MannEtal09b LongKaha13 RamaEtal12b LongEtal11 DetrEtal07 BurkEtal12 RamaEtal10 HartEtal05 LongKaha12b SommEtal12 ReccOKee89 PolyEtal07 MortEtal07 SedeNorm07 | No registry |
| C2 Psychonomic abstracts | 3 | LohnEtal10 LohnEtal09 PolyEtal06 | PsycEXTRA partial (see below) |
| C3 SMP abstracts | 3 | MillEtal07e vanVEtal06 CrutEtal12 | No registry |
| C4 Cosyne abstracts | 2 | RamaEtal13 BurkKaha13 | No registry; venue typo "coysne" |
| C5 OHBM/CNS/CAC/ISMRM abstracts | 4 | PolyEtal05b BranEtal04 HealEtal12b CordEtal02 | No registry; CordEtal02 hold |
| D1 Software | 20 | Depo18 MannEtal23b Varo10 Eust19 Gaut08 Mann21d TorvHama05 CapoEtal17 Keck07 LeSa99 deCa05a deCa05b ChanLin01 Smit05 Baas05 Scav05 Beaz05 Schl07 Stra06 FitzEtal25 | No route. 11 have no URL. FitzEtal25 has DataCite |
| D2 AI model/service | 3 | SingEtal24 ChatGPT Qwen26 | No route; SingEtal24 has a 331-name byline |
| D3 Web pages / grey literature | 9 | ContPrev23 FoodAdmi20a FoodAdmi20b ContPrev24 Nati24a Nati24b Amer23c NetwLab25 Gede24 | `howpublished` unverifiable; no route |
| D4 Patents | 3 | CoopEtal04 LittEtal98 EchaEtal00 | No patent number in entry |
| D5 Journal article or chapter typed @misc | 5 | DiazEtal15 SpenEtal03 FellEtal01a WilsEmmo03 Yama08 | Type only for SpenEtal03. Crossref/PMC record already found |
| D6 Lecture, report, test, story, quotation | 6 | Hawk99 Laks01 WallEtal57 Wech97 OGra11 HeraCE | No route |
| E1 arXiv | 4 | JianEtal24 LiuEtal24 YangEtal24 AlvaEtal05 | Name partition; corporate/"others" byline; printed vs repository name |
| E2 bioRxiv | 6 | GoldEtal21 XieEtal21 JainHuth18 TsitEtal19 ZimaMann21 BetzEtal19 | 4 have unpinned multi-version DOIs; 2 have API author-order/partition conflicts; results are policy 1 |
| F External-evidence hold | 1 | Samm69 | Jr suffix (DBLP) vs Crossref/citation; IEEE Xplore bot wall |

Totals: 49 Crossref-registered proceedings; 21 no-DOI proceedings; 32 abstracts; 46 misc
(including 5 mistyped articles and 6 other); 10 preprints; 1 hold. There are **no PsyArXiv
entries in this group**. CerEtal18, KhanEtal25, VodrEtal16, ZhenEtal19 and AbdeEtal21 are in
the unresolved set but in another group file; rules for them are in §2.9.

## 2. Routes and acceptance rules

**Universal acceptance contract.** It applies to every route and follows the arXiv/bioRxiv pattern.

1. Name an authority for each class. Save the raw body with URL, retrieval time and sha256 in
   the separate source cache, never the main cache.
2. Bind identity to an exact identifier: DOI, NeurIPS hash, PMLR `v{vol}/{slug}`, Anthology ID,
   arXiv id+`vN`, bioRxiv DOI+`vN`, Zenodo version DOI, GitHub `owner/repo@tag`, patent number,
   or archived-snapshot URL+timestamp.
3. Compare every field present in the entry. A field without a verifier blocks the entry until a
   verifier exists or a named human adjudicates it. Never drop the check.
4. Use existing `author_evidence` for ordered full bylines. Do not parse organizations as people.
5. The source must not borrow fields from another version or work: no journal version for a
   preprint, no reprint year for an original, no latest arXiv version for an older one.
6. A repeat run makes 0 requests and writes 0 reviews.
7. LLM, OCR and assistant findings go through `attach-evidence` only. Approval is either
   deterministic source comparison or `verification_cli approve --reviewer <human>`.

### 2.1 Crossref proceedings near-misses (A1-A7, 49): extend the comparator, no loosening

1. **`@conference` equals `@inproceedings`.** BibTeX defines CONFERENCE as identical to
   INPROCEEDINGS. Map `conference` to `proceedings-article` in `expected` and treat `booktitle`
   the same way. This affects 20 entries.
   - *Alternative:* edit the types to @inproceedings in cdl.bib. That invalidates the entries
     and needs re-verification. (User question.)
2. **Enumerated booktitle series aliases.** Model them on `normalize_journal`: an explicit table
   of house form to source-container pattern, one row per series. Examples: ICASSP, CVPR,
   EMBC/IEMBS, ICRA, IROS, BigData, ISEC, BHI, SenSys, MobiSys, HotMobile, UIST, MobiCom, VLCS,
   SIGIR, ICML(ACM), EMNLP, NAACL, ACL, COLING, Interspeech/Eurospeech/ICSLP, SciPy, CCN.
   Acceptance requires all of the following:
   - (a) The container matches the row's pattern exactly after normalization, with only the
     leading year, ordinal and parenthetical acronym stripped.
   - (b) The year inside the container equals the cited `year`.
   - (c) If the house form contains an ordinal ("Proceedings of the 14th ..."), the ordinal must
     match.
   - (d) A named human signs the table once, as done for documented journal variants.

   This is roughly 25 table rows for 41 entries. Demo tracks are separate rows: EMNLP-demos is
   not EMNLP main.
   - *Alternative:* rewrite the booktitles to the publisher container (41 edits). (User question.)
3. **Verifiers for the remaining fields:**
   - `organization`: an exact enumerated corporate list (IEEE, ACM, ISCA, PMLR, Springer) that
     must equal the Crossref `publisher` under the existing corporate-variant list.
   - `editor`: the Crossref `editor` array, compared with `author_evidence`.
   - `address`: accept only if it equals the Crossref `event.location` (conference city) or the
     publisher's documented seat, taken from an enumerated human-signed table (ACM to
     "New York, NY, USA"). Otherwise it blocks.
   - Values like "Citeseer", "Salk Institute, San Diego" and "San Francisco" are not
     organizations of the work. They are correction candidates: remove them or keep them with a
     human note. (User question.)
4. **Registry records with name in `family` only** (DengEtal09 "Kai Li", "Li Fei-Fei"): accept
   when the token sequence of `family` equals the citation's given initials plus surname tokens,
   exactly. This is not partition-agnostic fuzzy matching. It fixes the "Missing or incomplete
   given names" cases in XiaoEtal10, PennEtal14, HalpEtal16, HeusMann18 and LiEtal18, if the
   cached records show that pattern. This has not been verified for each one.
5. **Springer LNCS book-chapter for `@inproceedings`** (FiscMode03, dBakEtal08, MallEtal97 if
   found): accept `book-chapter` only when the Crossref record carries `event` metadata or an
   LNCS/LNAI ISSN from an enumerated list. The chapter's container is the series or volume title,
   so booktitle goes to the alias table.
6. **Reprint rule** (AltmSchu02): the Psychology Press 2019 reprint (10.4324/9781315782379-49)
   verifies title, authors and pages 65-70. The year must come from the proceedings ordinal
   ("Twenty-Fourth Annual Conference" = 2002, a deterministic series table). Never use 2019.
   Pages 65-70 are then a source-backed addition.
7. **Source-backed corrections** (edit batch like arxivfix001):
   - HaonEtal16 bylines, DengEtal09 pages
   - Added pages: PennEtal14, IyyeEtal15, Kipp01, XiaoEtal10, DolfWend98
   - WolfEtal20 booktitle and byline
   - Years for ICASSP-1990/1992, HuggEtal06 and MakaEtal06
   - Each needs two agreeing sources: Crossref plus ACL Anthology `.bib`, IEEE/CVF open-access
     page, local PDF (PennEtal14, IyyeEtal15, HuggEtal06, AndeEtal16 and BleiLaff06 have local
     PDFs by key), or publisher page.
   - YingEtal92, AndeEtal16, KluyEtal16 and RagaWill18 stay unresolved until the exact record is
     identified.

### 2.2 NeurIPS (B1, 6)

- **Authority:** `proceedings.neurips.cc/paper_files/paper/{year}/hash/{hash}-Abstract.html`.
  - Its `citation_*` meta carries title, "Family, Given" authors, `citation_journal_title`,
    `citation_volume` and `citation_publication_date`.
  - The companion metadata JSON carries `page_first/page_last`, and the paper BibTeX is also
    published.
  - Probe: LiuWang16 page returned volume 29, authors "Liu, Qiang; Wang, Dilin", date 2016, and
    no pages in the meta.
  - `verification/neurips_record_lookup.py` exists for the metadata document.
- **Identity:** the paper hash. Discovery is by exact normalized title on that year's index page.
  One title hit plus an exact year is required.
- **Acceptance:**
  - Title, ordered byline, year and volume must equal the publisher record.
  - Pages must equal page_first-page_last.
  - Booktitle is "Advances in Neural Information Processing Systems".
  - Publisher/editor must match the BibTeX record if present.
- **Missing fields:**
  - ParkPill12, LiuEtal18 and LiuWang16 lack volume and/or pages.
  - The existing rule "source supplies a field absent" blocks them.
  - This yields correction proposals, applied only with a second agreeing source (PDF front
    matter or the NeurIPS BibTeX counted as the same provider, so the PDF is needed).
- **Year trap:** RaoHowa08 has editors Platt/Koller/Singer/Roweis, which is NIPS 20 (the 2007
  meeting, published 2008). Record the proceedings year the publisher states. Whether
  2007 or 2008 is correct is unknown.
- **YangEtal13:** a NeurIPS 2013 *workshop* with no proceedings volume. The "volume 11" is
  unexplained. Human route: workshop page plus PDF, a named-human decision.
- **DBLP is not usable.** The probe got an anti-bot page ("Making sure you're not a bot!") from
  dblp.org/search/publ/api.

### 2.3 PMLR (B2, 5)

- **Authority:** `proceedings.mlr.press/v{vol}/{slug}.html`. Its meta carries
  `citation_title/author/firstpage/lastpage/publication_date/conference_title`. The page's
  embedded BibTeX carries `volume` and `series = Proceedings of Machine Learning Research`.
  - Probe on AchiEtal17 (v70/achiam17a): Achiam, Held, Tamar, Abbeel; pages 22-31; 2017-07-17;
    volume 70. These match the citation.
- **Acceptance:** exact title, byline, pages, year and volume (when cited). Booktitle goes
  through the alias table (the bib's booktitle is "Proceedings of the 34th International
  Conference on Machine Learning"). The organization "PMLR" must equal the publisher.
- **Corrections:**
  - RangEtal14: booktitle typo "Intellience" (AISTATS 2014, PMLR v33).
  - ParkEtal24 (@conference, v235, 39643--39666): type rule plus volume check.

### 2.4 ACL Anthology (A3, B3)

- **Authority:** `aclanthology.org/{ID}.bib` (probe for ZengEtal14 = C14-1220: title, 5
  authors, pages 2335--2344, COLING 2014 long booktitle, publisher DCU & ACL).
- **Identity:** the Anthology ID. For DOI-registered papers, the Anthology bib is the second
  corroborating source.
- **Acceptance:** same field rules as 2.1; the booktitle goes through the alias table.

### 2.5 CogSci and other old proceedings (B4, B5, 9)

- **CogSci:**
  - eScholarship HTML/search returned **HTTP 403 (CloudFront)** to a scripted request.
  - Its OAI-PMH endpoint works (`verb=Identify` OK), but `ListSets` exposes only `everything`.
    So retrieval needs a known item ark, and discovery is manual.
  - Whether eScholarship holds 1995, 2004 and 2008 volumes is **unknown**.
  - The older volumes are at csjarchive.cogsci.rpi.edu (PDF).
  - **Rule:** a documentary route. The proceedings PDF (paper plus volume front matter giving
    the year and pages) is captured and hashed. Deterministic text comparison of title and
    byline is done against the extracted first page. Approval is by named human unless an
    eScholarship OAI record exists, in which case compare OAI Dublin Core deterministically.
  - ShafGood08 has pages 1632--1637 to check. Its organization "Cognitive Science Society
    Austin, TX" is malformed (a correction candidate).
- **PellMoor00 (ICML 2000, Morgan Kaufmann), BernClif94 (AAAI KDD-94 workshop, AAAI tech
  report), BartEtal04c and MuelShif06 (ICDL), DeloEtal01 (venue suspect), MallEtal97 (ICANN'97,
  probably LNCS 1327, DOI unknown):**
  - Run discovery first: a Crossref query with the series, and the AAAI digital library for
    BernClif94.
  - Otherwise, the documentary PDF route with named-human approval.

### 2.6 Conference abstracts (C, 32)

- **No registry exists for SfN, SMP, Cosyne, OHBM, CNS or CAC.** Most are Kahana/Manning-lab
  abstracts.
- **PsycEXTRA** (Crossref type `dataset`, container "PsycEXTRA Dataset", DOIs 10.1037/e...)
  holds some Psychonomic abstracts. Cached examples:
  - LohnEtal10: exact title and full ordered byline, 2010.
  - SedeNorm07: title differs, 2007.
  - PolyEtal06: title exact, **Morton missing**.
  - PsycEXTRA does not name the meeting, and its DOI suffix year (e.g. 2012) is the deposit year.
- **Rule:** PsycEXTRA can verify title, ordered byline and year. It never verifies booktitle,
  address or meeting. The meeting still needs the program or abstract book, or a named human.
  PolyEtal06 stays a byline conflict.
- **Default route: named-human adjudication with an evidence packet.** The packet holds the
  program or abstract-book PDF or URL if findable (SfN itinerary archives, Psychonomic abstract
  books, Cosyne program PDFs; availability for these years is unknown), plus a local poster if
  any. Record `approve --reviewer <name> --source <url/pdf sha> --note`.
- **Cleanup edits to decide first:**
  - "coysne" should be "Cosyne".
  - Types are mixed: `@conference` with `publisher = Society for Neuroscience` versus
    `@inproceedings` with a booktitle. Decide one house form for abstracts before approving,
    since an edit afterwards invalidates approvals.
- **CordEtal02:** decide which work is cited (see holds).

### 2.7 Misc (D, 46)

**D5 mistyped articles (5).** Retype SpenEtal03, FellEtal01a, DiazEtal15 and WilsEmmo03 to
`@article`, and Yama08 to `@incollection` (LNCS chapter 10.1007/978-3-540-88853-6_1). Move
DiazEtal15's `booktitle` to `journal`. The existing Crossref/PMC route then applies. WilsEmmo03
still needs a second source because Crossref drops Emmorey. These are edits (user question).

**D1 software (20).** "Verified" means all of the following:

- (a) **Identity:** a persistent identifier with the cited version. The order of preference is:
  - a Zenodo/DataCite version DOI;
  - else the project's CITATION.cff or stated preferred citation at a tag;
  - else the official homepage, or a GitHub repo plus a tag or commit existing in the cited year.
- (b) **Title:** equals the project's own name or its CITATION.cff title (no paraphrase).
- (c) **Authors:** equal the CITATION.cff or DataCite creators, or the homepage's stated
  author(s). GitHub `owner.login` alone never establishes a person's name.
- (d) **Year:** equals the release/tag year, the DataCite publicationYear, or the year stated by
  the project's own citation text.
- (e) **URL:** resolves (200 after redirects), and the page is saved with its hash.

GitHub API probe (Depo18): repo created 2018-04-20, which matches year 2018, but there is no
author name. That is an identity/year signal only.

**DataCite name parsing:**

- Zenodo-GitHub records put the full name in `familyName` with no `givenName`. For FitzEtal25
  this is "Paxton Fitzpatrick" in DataCite and the Zenodo API alike.
- Compare the full-name token sequence exactly. FitzEtal25 then still fails on the "C" initial
  and needs a correction or a human decision (lab member).
- Mann21d says `publisher = Zenodo` but has no DOI, so it needs DOI discovery. Its author is a
  lab member.
- For the 11 entries without a URL (deCa05a/b, Smit05, Baas05, Scav05, Beaz05, Schl07, Stra06,
  Keck07, LeSa99, ChanLin01), find the homepage first.
- ChanLin01 (LIBSVM 2001 software): the project now asks for the 2011 ACM TIST paper. **Do not
  substitute.** Verify the 2001 software citation against the homepage's historical citation
  text via a Wayback snapshot, or send it to a human.
- Expect about half of these to need human decisions on the year or version (which one was
  cited is unknowable from the entry).

**D2 AI model/service (3).**

- SingEtal24: the Llama 3 model card has 331 names. The authority is the HF model card
  (`hf_fs cat hf://models/meta-llama/...README.md`). The correct repo id is unknown; there are
  several Llama 3 cards. The byline must match the card's contributor list, and the card
  revision (commit) must be pinned.
- ChatGPT and Qwen26: web-page rule. The corporate author must equal the publisher, as an
  organization.

**D3 web pages (9).** "Verified" means all of the following:

- (a) The URL resolves, or there is a Wayback snapshot within the cited year. Pin the snapshot
  timestamp for dynamic pages (FastStats, NIMH statistics, the FDA database).
- (b) The page's own headline or `<title>`, minus an enumerated site-name suffix, equals the
  citation title.
- (c) The corporate author equals the page's owning agency or organization as stated on the page
  (organizations stay organizations).
- (d) The year equals the page's stated publication, release or "last reviewed" date, or the
  document date.
- (e) The raw HTML/PDF is saved with sha256.

Deterministic comparison is possible. Recommend human sign-off for the first batch of this new
route. Gede24 is an article hosted on a product vendor's site (frenzband.com); whether it is the
original publication is unknown, so it goes to a human.

**D4 patents (3).** The entries have no patent numbers. Discover them on Google Patents or USPTO
by inventor and title. "Verified" means the patent number, exact title, ordered inventors and
year match, with the grant or publication year chosen by house rule (user question). Assignee
companies are never authors.

**D6 other (6):**

- WallEtal57: a technical report cited as @conference; retype to @techreport, then the DTIC
  record or report PDF.
- Hawk99: a public lecture; hawking.org.uk lecture page, with human sign-off.
- Laks01: a symposium lecture. The published symposium volume, if any, is unknown.
- Wech97: PsycTESTS 10.1037/t49755-000 has an exact byline and 1997. The title adds
  "--Third Edition" versus the cited "Scale-III (WAIS-III)", which is a title alias needing
  human sign-off.
- OGra11: "Pie man" story; source unknown (The Moth?), so human.
- HeraCE: an ancient quotation with no verifiable edition. Human decision: accept with a note,
  or recast to a specific translation.

### 2.8 Preprints (E, 10)

First re-run reassessment for the 6 bioRxiv entries under preprint policy 2 (cache only).

- **Version pinning (applies to all):** an unversioned identifier must be pinned before approval.
  - Proposed rule: pin to the **latest version posted on or before 31 Dec of the cited year**.
  - If more than one version falls in that year and they differ in title or byline, a human
    chooses.
  - Never pin a later version than the cited year. Never replace with the journal version.
  - This conflicts with arxiv_review's documented "unversioned = current version" semantics
    (arxiv_review.py:3-4), so a policy decision is needed (user question).
  - Applies to GoldEtal21, XieEtal21, JainHuth18, TsitEtal19 (bioRxiv; "multiple repository
    versions") and JianEtal24, LiuEtal24, YangEtal24 (arXiv, unversioned 10.48550 DOIs).
- **JianEtal24:** correct `D d l Casas` to `D {de las Casas}`. Accept the name when the API full
  name and the HTML "Casas, Diego de las" have the **identical token multiset and order modulo
  the comma inversion**. That is an exact rule for the inverted form, not fuzzy.
- **LiuEtal24 (DeepSeek-V3) and YangEtal24 (Qwen2.5):** the local bylines are truncated with
  `others` (15 and 11 names). The repository adds the corporate names DeepSeek-AI and Qwen.
  - The rule must choose one of:
    - (a) the full ordered person byline exactly as on the pinned version;
    - (b) a corporate author `{DeepSeek-AI}` / `{Qwen Team}` only if the pinned PDF title page
      prints the corporate byline;
    - (c) a truncated prefix plus `others`, accepted only if it is an exact prefix of the source
      person list, excluding the organization.
  - Recommend (b) where printed, else (a). (User question.) KhanEtal25 follows the same rule.
- **AlvaEtal05:**
  - Title typo correction is source-backed (PDF v2 plus repository).
  - Byline: printed v2 "Ignacio Alvarez-Hamelin" versus repository "Jose Ignacio". Proposed
    precedence: the printed byline of the pinned version is authority for the citation, and
    repository metadata is secondary. So keep `I Alvarez-Hamelin` and record the conflict.
  - Needs named-human approval under the current hold.
  - CerEtal18 is the same kind (accented Guajardo-Céspedes, Sheng-yi Kong from the PDF). Attach
    the PDF finding as main-cache external evidence, then have a human adjudicate the whole byline.
- **ZimaMann21** (v1 pinned; API reverses author order): the version HTML `citation_author` and
  the PDF title page outrank the details API for order. Accept only if HTML and PDF agree; record
  the API disagreement. Our own paper, so it needs a human confirmation.
- **BetzEtal19:** confirm "Farnaz Zamani Esfahlani" on the version HTML and PDF, then correct to
  `F {Zamani Esfahlani}` (source-backed edit).
- **VodrEtal16 and ZhenEtal19 (other group):** retrieve the earliest version's Atom/HTML
  (`vN` explicit). Pin the version whose byline equals the citation. Never adopt authors added
  later.
- **PsyArXiv (other group; 6 leads):** the OSF API works. The probe
  `api.osf.io/v2/preprints/?filter[provider]=psyarxiv` returned an id like `5djx6_v1` with
  `version`, `date_published` and relationships `bibliographic_contributors`, `versions` and
  `identifiers`.
  - Route: preprint id `{guid}_v{N}`, then attributes (title, date_published, version, doi),
    then `bibliographic_contributors` (ordered, with users' full_name/given/family), then the
    DOI 10.31234/osf.io/{guid} via DataCite as the second source.
  - The same pinning and ordering rules apply. No journal replacement (OSF may expose
    `article_doi`; record it, never substitute it).

### 2.9 Holds

- **Samm69:** DBLP says John W. Sammon **Jr.**; the citation and Crossref omit it. IEEE Xplore
  shows a robot check, and there is no local PDF (checked by key in the Dropbox library).
  - Needs the original byline: a library PDF or the publisher's citation export.
  - When the byline is obtained, add the suffix only if printed. Named human.
- **CordEtal02:** the local PDF is the ISMRM 2002 abstract (vol 10, author order Cordes,
  Haughton, Arfanakis, Carew, Maravilla). The citation's vol 20(4) 305-317 is the *Magn Reson
  Imaging* article, with a different author order.
  - The human must choose the cited work. Then either correct it to the MRI journal article
    (Crossref route) or to the ISMRM abstract (drop the journal coordinates, fix the order).
- **AlvaEtal05, JianEtal24, LiuEtal24, YangEtal24:** above. CerEtal18, KhanEtal25, VodrEtal16
  and ZhenEtal19 are in another group; rules above.

## 3. Order, pilots, success criteria

Every pilot must meet these conditions:
- The 60-case benchmark stays 60/60 with 0 false accepts.
- Explicit negative controls stay unresolved.
- The repeat run makes 0 requests.
- Prior approvals are unchanged.

1. **Pilot A: comparator rules** (conference synonym, series alias table v1, organization,
   editor and address verifiers, family-only names). This is code plus a human-signed alias
   table, with no bib edits. Keys: WangEtal10b, ChenEtal22, CoppEtal17, DengEtal13, Subb13,
   NguyEtal16b, LiEtal16, TianEtal16b, BambEtal90, Etha19.
   - **Negative controls that must stay unresolved:** DengEtal09 (pages), HaonEtal16 (byline),
     YingEtal92 (year), and EMNLP-demos versus EMNLP main (WolfEtal20).
   - **Success:** at least 9/10 verified, with 0 approvals for the controls.
   - **Then:** expand to all 25 formal-only entries (list in `proc-best.txt` analysis: CoppEtal17
     DengEtal13 Subb13 NaroEtal11 KellEtal10a BlakEtal08 WangEtal10b BleiLaff06 ScheEtal02
     NguyEtal16b LiEtal16 TianEtal16b LiEtal17b TianEtal17 TianEtal18 LiZhou18 TianEtal20b
     LiEtal20 CarvEtal22b StonEtal25 ChenEtal22 Etha19 HewiMann19 BambEtal90 FiscMode03).
2. **Pilot B: publisher-site routes** (PMLR, NeurIPS, ACL Anthology). Keys: AchiEtal17,
   JianLi16, FaraEtal18, ParkEtal24, VaswEtal17, LiuWang16, ZengEtal14.
   - **Success:** identity bound by hash, slug or ID; every field compared. Missing-field entries
     yield correction proposals, not approvals.
   - **Negative control:** a title hit in the wrong year must abstain.
3. **Batch C: bioRxiv reassessment under policy 2** (cache only), then the version-pin rule on 4
   entries after the user decides.
4. **Batch D: source-backed correction batch** (like arxivfix001): HaonEtal16, DengEtal09,
   JianEtal24, BetzEtal19, AlvaEtal05 title, RangEtal14, PennEtal14, IyyeEtal15, Kipp01,
   XiaoEtal10, DolfWend98, the 5 mistyped misc, and WallEtal57's type.
   - Each needs two agreeing sources (Crossref plus Anthology, PDF, or publisher page).
   - Stage, assert unrelated entries and keys are unchanged, then run production verification.
5. **Pilot E: software, web and AI documentary route.** Keys: FitzEtal25, Mann21d, MannEtal23b,
   Depo18, ContPrev23, Nati24a.
   - **Success:** evidence packets (raw hashed bodies plus field table) are produced, and
     approvals happen only where all fields match exactly.
   - First batch: named-human sign-off on the route.
6. **Human packets:** 32 abstracts, CogSci/old proceedings, patents, D6, Samm69, CordEtal02,
   AlvaEtal05 byline, ZimaMann21, and the LLM-truncated bylines.
   - Batch 10 per sitting. Each packet holds the source URL or PDF hash, the field table, and a
     proposed decision. The human runs `approve --reviewer`.

### Expected share (estimates, not measurements)

| Outcome | Approx. n | Classes |
|-|-|-|
| Automatic, no bib edit (after new rules/routes) | ~30 (19%) | 25 formal-only Crossref, plus about 5 PMLR/NeurIPS/Anthology |
| Automatic after source-backed correction batch | ~40 (25%) | Remaining Crossref substantive, NeurIPS/PMLR missing fields, mistyped misc, preprint corrections/pins |
| Documentary route (deterministic, first batch human-signed) | ~20 (13%) | Web pages, DataCite/CITATION.cff software |
| Named-human adjudication required | ~68 (43%) | 32 abstracts, most old software, patents, D6, CogSci/old proceedings, holds |

Unknown: how many abstracts have online programs; eScholarship coverage of CogSci 1995, 2004 and
2008; the exact identity of KluyEtal16, YingEtal92, DeloEtal01 and MallEtal97.

## 4. Questions for the user (each blocks a route)

1. `@conference`: comparator synonym (recommended; no edits) or retype 20 entries?
2. Booktitle: a human-signed series alias table (recommended; about 25 rows cover 41 entries),
   or rewrite booktitles to the publisher container?
3. Unverifiable `organization`/`address`: verify against enumerated tables (recommended), or
   remove the non-standard values (Citeseer, "San Francisco", etc.)?
4. Unversioned preprints: pin the latest version on or before the cited year (recommended), v1,
   or current?
5. Truncated or corporate bylines (DeepSeek, Qwen, Khan, Llama): corporate if printed, else the
   full list (recommended)?
6. Printed byline versus repository metadata (AlvaEtal05, CerEtal18): printed pinned-version
   byline wins (recommended)?
7. Abstracts: accept named-human approval from the lab (Jeremy) using a packet (recommended),
   given that no registry exists?
8. Software year semantics: release or tag year of the cited version (recommended), versus
   access year.
9. Patent year: grant year (recommended) or filing year?
10. CordEtal02: MRI journal article or ISMRM abstract?
