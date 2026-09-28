# Plan to resolve all 2,753 unresolved entries — drafted 2026-09-22

Baseline: 3,669 metadata_verified / 2,753 needs_review (commit db310f3).
Five read-only planning agents classified every unresolved entry from cached
evidence. Detailed plans (per-key tables, pilots, negative controls):

| Group | Entries | Plan |
|-|-|-|
| Articles, no unambiguous match | 1,945 | [plan-articles.md](plan-articles.md) |
| Books, chapters, theses, reports | 413 | [plan-books.md](plan-books.md) |
| Proceedings, preprints, misc | 158 | [plan-proceedings.md](plan-proceedings.md) |
| DOI coordinate / suffix conflicts | 136 | [plan-doi-conflicts.md](plan-doi-conflicts.md) |
| Correction / retraction notices | 101 | [plan-notices.md](plan-notices.md) |

Classification data is in `data/`. Estimates below are the agents' estimates
from cached evidence, not measurements.

## Decisions recorded from the user (2026-09-22)

- Retractions: flag each for the user; nothing automatic. (None found on cited works in cached evidence.)
- Content-only errata with fully matching metadata: auto-verify, notice kept in the report only (no BibTeX note).
  If the erratum text can't be retrieved, decide on a batch review page.
- Coordinate conflicts: auto-correct when publisher and PubMed agree; otherwise human.
- Preprint later published: default swap to the published version under a NEW key and remove the preprint entry,
  but ask per entry first. Removing old keys without a usage check is acceptable.
- Add verified DOIs to entries once a full match is verified.
- @misc: registry (DataCite/Zenodo/GitHub release) or live page match counts; dead links go to the user.
- Named reviewer: Jeremy Manning only.
- Unverifiable entries: local PDF evidence, then the user's sign-off (recorded as human-verified).
- `publisher` on @article: drop the field.
- Year: the print year wins (accept when print and issued both equal the cited year; correct the ~24 online-year citations).
- Entry types: convert @conference → @inproceedings and titled-chapter @inbook → @incollection in cdl.bib.
- Printed PDF of the cited version beats repository metadata on bylines.
- Corporate authors: match the printed byline exactly.
- APA `10.1037//` DOI forms may be used as lookup keys only; acceptance still needs a full match.
- Conference abstracts (32): flag for removal (list them for confirmation before deleting).
- External APIs: ProQuest via the library login only; no personal API. Skip; theses use local PDFs + sign-off.

## Path forward (phased)

Every phase keeps the existing guarantees: frozen proposals, staging diff limited
to the batch, all cite keys kept (except the approved preprint swaps and removals),
zero-request/zero-write repeat, exact fresh restore, tests + benchmark green,
local commit per batch.

**Phase 0: false flags and matcher rules (code only, no bib edits).**
Tie notice/coordinate/suffix flags to the cited work's own DOI (clears 22 notice
and 56 coordinate false flags, which fall back to their real issue); collapse
byte-identical Crossref records; print-year rule; duplicate-DOI rule (APA `//`
twins, reissued chapters, preprint twins); documented journal variants; editor /
address / organization / chapter checkers (parent-book Crossref record or LoC);
widened LoC record parser. Each rule gets real positive and negative controls.

**Phase 1: policy edits (bulk, mechanical).** Drop `publisher` from @article;
convert @conference and @inbook types; print-year corrections. Note: this changes
fingerprints of some *already verified* entries, so they re-verify (mostly from cache).

**Phase 2: source-backed correction batches.** pmccoord006 (7), artno001 (15,
new article-number rule), pmccoord007 (~15), suffix003 (~11); article single-field
corrections where Crossref and PubMed agree (pool of 513); PubMed lookups by APA
`//` DOI form and by volume/page/author; add verified DOIs.

**Phase 3: new source routes.** PMLR / NeurIPS / ACL Anthology adapters; bioRxiv
re-judge under policy 2 plus version pins; PsyArXiv via the OSF API; Zenodo/DataCite
and CITATION.cff for software; the PEP JSON; chapter two-layer rule (catalogue edition +
chapter record or inspected TOC page image); local PDF library evidence.

**Phase 4: user-approval queues.** Preprint→published swap proposals (per entry);
removal list for the 32 conference abstracts; 79 errata acknowledgements.

**Phase 5: human review page.** One review page (artifact with a shared decision
store, or static HTML + CSV import) for everything still unresolved: fields, a
per-source match grid, local PDF snippet, a suggested decision, bulk-accept per
class; decisions import through a CLI that checks fingerprints.

Rough expected outcome (agent estimates): ~1,300–1,550 entries resolve through
phases 0–3; ~1,200–1,450 reach the user (roughly 800–950 articles, 190–280 books,
~70 proceedings/misc, ~25 coordinate cases, 79 errata). The human share is the
biggest uncertainty and shrinks with each route that works; it is reported after
each phase.

## Revision after user feedback (2026-09-22, later)

The user can make at most ~100 decisions, not ~1,200. Revised rules:

- **One authoritative source is enough.** If *either* Crossref or PubMed holds the
  record for the cited work, the citation may be verified or corrected from it (no
  second, agreeing source required). Identity must still be pinned by the work's own
  DOI/PMID, or by exact title, first author, year and venue, so the rule changes where
  field values come from, not how loosely identity is matched.
- **Local-PDF acceptance, after a hard benchmark.** Code-extracted text only, with the
  LLM limited to locating lines. The benchmark must use *subtle* planted errors, e.g. a
  wrong page or issue number that also appears elsewhere in the PDF (a statistic, a
  figure number, a reference-list entry, a received date, a running header of another
  article). Matching must be position/role-aware: bibliographic header/footer/citation
  line of the cited version, never body text or references. Zero false accepts
  required before enabling.
- **Class approvals by 10-entry random samples** (20 for multi-field fixes); an error in
  a sample reopens the rule, not just the entry.
- **Everything reaching the user is grouped by pattern** so one response covers a
  group (e.g., "accept all 40 'digitized-later year' cases"); individual review only
  for true one-offs.
- **Leftovers:** count them first, then decide data-driven; the goal is to find another
  verification mechanism, not to remove them by default.

## Spot-check findings (2026-09-24, first 9 verdicts)

- Author corrections must use the house format: initials without periods, one per given
  name, **all initials the source gives** (M E Smith, D C Young, N B Turk-Browne); full
  given names are converted to initials. The first proposals copied full given names.
- A cited `volume(issue)` split may keep the issue only when a source states it. Look it up
  (PubMed, publisher page); if nothing confirms it, drop it (volume `10(1)` becomes `10`).
  The first proposals carried the citation's own issue number as if it had been checked.
- Both rules are fixed before any proposal from an affected class is applied; affected
  spot-check samples are redrawn under the fixed rules.

## Preprint versions (user decision, 2026-09-24)

Preprints always cite their **latest** version (year = that version's date; pin the
version where the server supports it). A preprint that has been **published** is replaced
by the published version (new key; old entry removed). Replacements are prepared as one
list for the user to approve, per the earlier decision.

## Spot-check completed (2026-09-24/25) and resulting decisions

All 54 sampled entries decided: 49 correct, 5 wrong. Decisions:
- **No name suffixes** (Jr, Sr, II, III, IV): never added; the 27 existing ones are stripped;
  the comparator ignores suffixes.
- **Initials everywhere:** full given names are converted to initials; compound or unbraced
  surnames are held and checked against a source first.
- **Catalogue publisher names:** a same-firm longer form is a match; keep the house form.
- **Page ranges are never shortened** by a correction.
- **Single-source surname changes need corroboration** (a second source, or they are held
  when other cdl.bib entries spell the same author the cited way). Found after risky001
  applied Crossref's "Kounois" to MeyeEtal88 (reverted); the 10-entry spot-check missed it.
- **Year corrections rename keys** (user, 2026-09-25): GautEtal18 → GautEtal19 and
  HayeEtal14 → HayeEtal16 after their source-backed year fixes (check for collisions first).

## Research-pilot feedback (user, 2026-09-25): 30 correct, 20 wrong → rules

- **DOIs everywhere:** every entry gets a DOI when one exists, for the published,
  peer-reviewed version (e.g. eLife rather than bioRxiv for vanEEtal18). 3,214 of 6,422
  entries currently lack one. Verified entries were only given DOIs from a clean Crossref
  record; the remaining ones need identity established first (research route).
- **Issue ranges use `--`** (`3--4`), reversing the reviewer's majority-form reading;
  convert the 52 single-hyphen `number` ranges.
- **Proceedings names omit the year** (redundant with `year`); 5 existing booktitles.
- **`@book` has no `pages` field.**
- **Editions:** `5\textsuperscript{th}`.
- **Removals:** NetwLab25 (user). Beaz05, RamaEtal12b, SommEtal12: remove if no source is
  found, after searching the **SfN abstract planner** for the abstract year — add it as a
  permanent source for conference abstracts.
- Entry fixes: Hook69 title "The posthumous works of Robert Hooke"; Jame90 keeps
  "volume I"; ZimaEtal23 year 2023 (latest version) is correct.
- **Open PRs #87 and #88** (user, 2026-09-25): merge both into `bib-crossref-verification`
  once their references verify; they also serve as end-to-end tests of the machinery.
- **Pilot follow-up decisions (user, 2026-09-25):** Beaz05 is replaced by Beazley's 1996
  USENIX SWIG paper (new key); ScotEtal07 cites the chapter (@incollection); accented names
  keep their accents when a source prints them unaccented (ASCII limitation); Mink07 is
  switched to the 6th edition, which names Mink and is verifiable. PsyArXiv entries that
  store the DOI in `volume` (ZimaEtal23, GralFinn21, LuriEtal18, NussEtal18) move it to `doi`.
- **Keys always follow corrected metadata** (user, 2026-09-26): when a verified correction
  changes the year, first author or author count, the key is renamed per the ID rule. Every
  rename is logged in `verification/key-renames.json` (old → new) so citing papers can be
  updated. House address form `City, {ST}` stays (catalogue "drop the state" edits are
  dropped).
- **Proper ordinals everywhere** (user, 2026-09-26): every numeric ordinal in a text field
  (title, booktitle, journal, edition, ...) is written `N\textsuperscript{suffix}` with the
  correct suffix (`1\textsuperscript{st}`, `2\textsuperscript{nd}`, `30\textsuperscript{th}`);
  the comparator treats it as equal to "30th"/"Thirtieth" in sources.
- **Initials in publisher names without periods** (user, 2026-09-26): `W H Freeman`,
  `V H Winston` (reverses the 2B-i choice to keep "W.H.").
- **`bibcheck.py commit` gates on verification** (user, 2026-09-26): it verifies added/edited
  entries against GitHub master with `crossref verify --auto-review` and refuses to commit
  unresolved ones; it commits only the bib file (no `git commit -a`).
- **`bibcheck.py verify` checks citations too** (user, 2026-09-26): format check + citation
  verification of added/edited entries vs GitHub master + an offline library-wide status line;
  fails on any changed entry that is unresolved. `--no-citations` for format-only, `--all` for
  the whole library. `commit` shares the same check.
- **Replacements approved** (user, 2026-09-25): all 8 preprints in
  verification/apply-2026-09-28/replacement-candidates.json are replaced by their published
  versions (LeeEtal20 → LeeEtal20a to make room for LeeEtal20b; LuriEtal20 keeps "Keilholz").
- **Sign-off of pilot verdicts** (user, 2026-09-25): entries the user marked Correct on the
  research-pilot page (or whose fixes the user approved there) that no automated source can
  verify are recorded with `crossref approve`, reviewer Jeremy Manning, bound to each entry's
  exact current text. PR #87/#88 entries were not reviewed by the user and are not included.

## Cross-wave decisions (user, 2026-09-26; page https://claude.ai/artifact/5mBxCS3qzctwJdbpqcEEAY, copy in verification/research-2026-09-25/crosswave/decisions/)
- **Software/Zenodo releases:** always cite the *first* version, take the year from it, and do not put a version number in the citation (CapoEtal17/brainiak). (Preprints still cite the latest version.)
- **Countries in addresses:** drop a country when the source does not print it (Herb34, BuzsEtal94).
- **Ebbi85:** cite the 1885 German original (Über das Gedächtnis), not the 1913 translation.
- **Hwang:** keep each paper's printed name (G Hwang-Grodzins 2005, G M Hwang 2008).
- **OGra11:** year 2008 (recorded), key OGra08.
- **Shim94:** Shim94 → Shim95b (new), existing Shim95 → Shim95a (post-check key plan).
- **Conference abstracts:** 45 approved for removal. NOT abstracts (real articles, keep and verify normally): BeckEtal09, CronEtal94, MannEtal97, PailEtal00, SpieEtal18, TongEtal95. JohnRedi07b is a conference abstract: remove.
- **BenaEtal04:** title "Youmans Neurological Surgery".
- **Journal-alias repairs:** DiazEtal06, Murd68, MurdVomS67 approved.
- **Duplicates:** all 9 keepers approved; KahaEtal08b→KahaEtal08a approved, and drop the "a" suffix (KahaEtal08) if it is then the only KahaEtal08.

## Wave 1 decisions (user, 2026-09-26; copy in verification/research-2026-09-25/wave1/decisions/)
- 184/200 answered: 168 correct, 13 wrong, 3 unsure.
- **Rule (all waves): any entry without a source is dropped from cdl.bib** ("for anything without a source drop it from the current CDL.bib"). Wave 1: the 16 unanswered entries are all no_source → drop.
- **Rule: drop *all* conference abstracts** (LongKaha14 note), including SfN abstracts verified by the planner.
- Explicit drops: BranEtal04 (abstract), ContPrev24, Gede24, GreeEtal13 (cannot confirm), HeraCE, Keck07, Land95, MerzEtal12, Nati24a, Nati24b, LongKaha14.
- HealKaha14b → replace with the published version HealKaha16 (Psych Rev 123:23–69, 10.1037/rev0000015).
- Wech81: several Wechsler entries — keep ONE, drop the others.
- Kolo13: check whether "EdX" should be "edX".
- Unsure, no note (leave unchanged, ask): DougPeuc73, Mann06.
- (user, 2026-09-26) Keys must be correct: reusing a freed suffix for a different work (KahaEtal08c→KahaEtal08b, JacoEtal05d→JacoEtal05b) is fine.
- (user, 2026-09-26) Fix the formatter so it drops unprinted countries instead of adding them back.
- (user, 2026-09-26) Wech45, DougPeuc73, Mann06: resolve by manual web research. Accuracy first; consistency, scalability, generalizability second.

## Standing rules for the remaining waves (user, 2026-09-26) — no more per-entry manual checks
1. If an entry cannot be verified automatically, verify it by web search and cite the evidence (URL + verbatim quote) in the notes. If no evidence is available, drop the entry.
2. No conference abstracts. Before dropping one, verify it is *actually* an abstract and not a real paper; conference *proceedings* papers are fine.
3. All information must be *as printed* in the official record, up to the formatting differences bibcheck requires.
4. Flag anything needing the user, phrased where possible as a question about a *rule* that generalizes; single-entry questions only when unavoidable.

## Rule answers (user, 2026-09-26, round 1 of resolution questions)
- **Em dashes in titles:** `a---b`, no spaces, regardless of source spacing.
- **Conflicting official records** (usually the last page) when the printed PDF can't be seen: publisher page / Crossref wins; if the publisher is unreachable, Crossref, then PubMed.
- **Author names** that a record prints differently from the author's usual name (misprint 'Tulvig', missing middle initial 'Walter Pitts', 'Le Doux' vs 'LeDoux'): use the author's correct, most complete name; cite evidence from other records of the same author.
- **Unconfirmable optional fields** (chapter pages, editors, volume) on a verified work: remove the field.

## Rule answers (user, 2026-09-26, round 2)
- **Rule 1 beats earlier single-entry keeps:** no verifiable record → drop, even if previously marked "real article, keep" (PailEtal00, MannEtal97, TongEtal95).
- **Evidence accepted:** (a) image-only scans of the original printing (quote transcribed from the page image); (b) publisher pages read in a real browser when plain fetches are blocked; (c) an abstracting-index citation alone (PsycINFO/Scholar) is enough to keep an entry.
- **End pages:** when no source prints the end page, infer it from the next item's printed start page − 1 (printed TOC or next article).
- **Dissertation Abstracts International:** cite the dissertation itself as @phdthesis (school, degree year) from a catalogue/DataCite record.

## Defaults chosen by Claude for the remaining rule questions (2026-09-26; user may veto)
- Supplements: parent journal name; Number as printed (e.g. `4 Suppl 2`).
- Roman-numeral volumes: arabic numerals.
- Subtitle printed after a period: colon (house form).
- Multiplication sign printed as 'x'/'X' in metadata: `$\times$`.
- ACM-style "Volume <year>": omit Volume.
- Article printed in two parts: both ranges, `81--190, 257--339`.
- Software at its first version: the first version's title as registered (no version number).
- Web-only newspaper/magazine articles: cite the web version (url, online year); remove unconfirmable print volume/issue/pages.
- Truncated "and others" author lists: expand to the full printed list.
- Chapter in one volume of a multi-volume work: Editor = that volume's editor as printed.
- Person + corporate group byline: key from bibcheck's authors2key as it stands (consistency).
- A title quoting another title: keep the marks as ``X''.
- Compound spelled differently (highspeed vs high-speed): publisher/Crossref form (precedence rule).
- Renamed journals: the name as printed at publication.
- Items inside a journal's collective "Abstracts" record: abstracts → drop.
- Society proceedings: the printed year of the bound part (print-year rule).
- Cited reprint not found but the original is registered: replace with the original (new key).
- Record title with an evident misprint ('unhibited'): correct spelling, with evidence (same principle as author names).
- (default) NeurIPS/NIPS pages: the NeurIPS proceedings site (official publisher) beats Curran's reprint TOC.
- (default) Bilingual journal titles: the full title as printed on the journal.
- (default) A record giving only a first page is incomplete, not conflicting: keep the full range another official record (e.g. PubMed) prints.
- (default) Conference proceedings (NeurIPS/NIPS etc.): the conference year the proceedings print (NIPS 18 = 2005), not the bound volume's later print year (the existing post-check rule).
- (default) Organizational byline with individual contributors in metadata (DeepSeek-AI + 199 names): Author = the byline as printed on the paper (the organization alone), key from it (existing rule: corporate authors as printed).
- (default) Preprint vs a later journal article by the same authors with a different title and no registered relation: replace with the article only when its abstract/content confirms it is the same work (quote the evidence); otherwise keep the preprint (latest version).
- (default) A cited test/manual edition with no record: cite the original article that introduced the test (Wech45 precedent); if none, the PsycTESTS record.
- (default) Chapter pages where an official contents list confirms the start page but nothing shows the end page or the next chapter's start: keep the cited range if its start page matches (the field is partly confirmed); remove pages only when no part is confirmed. (Revisit batch-19 removals, e.g. RescWagn72, in reconciliation.)
- (default) Proceedings pages printed with a volume-numeral prefix (ICASSP 'I-185-I-188'): drop the prefix into Volume (Volume 1, pages 185--188).
- (default) Unconfirmable chapter of a confirmed single-author book: cite the whole book (remove chapter and pages), consistent with removing unconfirmable fields.
- (default) A title shared by several reports of one series (DAKOTA user's/reference/developers manuals) with nothing to tell them apart: cite the user's manual.
- (default) Python PEPs: @misc with howpublished = \url{https://peps.python.org/pep-NNNN/}, no institution (never printed).
- (default) Descriptive keys that never followed Author+YY (ChatGPT): rename to the rule key when corrected metadata applies ("keys must be correct", user).
- (default) Software with no registered release (GitHub-only): year = earliest date the project itself prints (first release/tag or repository creation), title/authors as in that first release; remove what no source prints.
- (default) Internal report known only from reference lists but reprinted in a registered book: replace with the registered reprint (verifiable), like published-replaces-preprint.
- NOTE for reconciliation: NeurIPS year must be consistent across batches (conference year default): SanbGrif08 (batch 01) vs RaoHowa07 (batch 24).
- (default) A work known only from reference lists of other publications (no catalogue, repository or abstracting-index record of its own): not a verifiable record → drop (WallEtal57). Abstracting-index records still count (user round 2).
- (default) Encyclopedia article with a print edition (no DOI) and a later online edition (DOI): cite the print edition as cited (print year wins); no DOI.
- NOTE for reconciliation: batch 20 keeps McGi63, Crai77 on reference-list evidence only → drop under the reference-list default.
- (default) Print book with a later e-book reissue carrying its own DOI/year/pagination: cite the print edition as cited (print year and pages), no DOI (same as the encyclopedia default).
- (default) Book year: the imprint year printed on the title page (as LoC records it) beats an earlier Crossref published-print date.
- NOTE for reconciliation: batch 22 removed MannEtal15's chapter pages as unconfirmable; try harder (MIT Press / Google Books contents of The Cognitive Neurosciences) before removing.
- (default) Chapter in a catalogue-confirmed edited book, evidenced only by other works' reference lists: the chapter is unverified → drop (reference-list default; ElliAshb88 in batch 18). A chapter of a confirmed single-author book is instead cited as the whole book.
- (default) Book year when the catalogue ("c2008") and the book's own printed copyright page / publisher record (2009) disagree: the printed copyright page wins (Wall09 stays 2009).
- (default) A cited end page equal to the next item's start page: keep it when an official record prints it (articles can share a page); infer next-start−1 only when no record prints the end page.
- (default) Part numerals in titles (`{II}. Title`): keep the period form (as printed; HEAD majority).
- (default) A spaced en dash used as a title dash: write `a---b` like the em dash rule.
- (default) Publishers whose official volume is the year (Hindawi): keep Volume = year as printed (unlike ACM's magazine "Volume <year>", which is omitted).
- (default) Offset digital-edition pagination in Crossref (AllpEtal94 411–442 vs print 421–452): a different edition; the print edition's pages win.
- (default) Locators (journal/volume/pages/year) and title point to different works by the same authors: the locators win (the work actually at that location), with the title corrected to it; if the authors don't match either work, drop.
- Open (single entry, kept as held for the user): SvenEtal24 third author printed with a family name written as initials ('Hoang NT').
- (default) A DOI that doi.org registers and the publisher's own article page prints (citation_doi), but that Crossref's API lacks (another agency or a lapsed deposit): keep it; the publisher page stands in for the missing registry title (McCaEtal06, 10.1609/aimag.v27i4.1904).
- (default) OCR that splits a printed number ('1 29' for 129) in a scan: treat as a scan transcription — the value may be set when the notes say "transcribed from a scan" and the context makes the reading unambiguous.
- NOTE for final apply: ElliAshb88 — batch 18 (reconciled) keeps it because Google's full text of the book itself shows the chapter title (p. 33); batch 30 drops it on reference-list grounds. The book's own text is primary evidence: keep (batch 18 wins).
- (default) OpenEdition-style issue designations ("2001/3, 6"): Number = the printed issue within the year (3); the running whole number is not cited.
- (plan) Group/corporate authors mangled by the bibcheck author formatter (KingEtal11 {RNS System in Epilepsy Study Group}) and the other check_bib-held forms (two-part page ranges etc.): fix the formatter rather than using Force; do this in one formatter pass before the final apply.
- (default) A corrected year that collides with an existing key of a different work (Buzs01→Buzs02): apply the house suffix rule to both (existing → a, new → b, by the key-order rule), as with Shim94/Shim95 (user: keys must be correct).
- (default) Datasets: the name as registered (DataCite/catalogue), e.g. {CELEX2}.
- (plan) Research route: a resolution title/author quote may serve as the identity quote when the researcher's identity quote has no saved body (browser/scan rule) — implement in the final route update.
- OPEN (asked; answered 2026-09-28, see "User answers 2026-09-28"): J Physiol "P" pages (Proceedings of the Physiological Society communications) — conference abstracts (drop) or proceedings (keep)? (BrinCrag72)
- (default) Page numbers printed in lowercase roman (front matter, e.g. `i--xii`): as printed (roman); roman→arabic applies to volumes only. Article numbers like `24ra22` (Science Translational Medicine): as printed.
- (plan) Research route: a chapter page range whose START page an official contents list confirms (kept under the partial-confirmation default) is approved with a `pages_start_only` flag (RescWagn72, Slam87) — implement in the final route update.
- (default) When the book itself (contents/full text) confirms a chapter's start page, the author's own later publication list or reference list may supply the chapter's remaining fields (author, title, end page) (RaaiShif81b); a reference list alone, without the book's confirmation, is still not enough.
- (default) Notices that cannot be read (paywall/CAPTCHA/no notice DOI) where Crossref and Europe PMC record no retraction or expression of concern: treat as errata; the entry is verified with a `notice_unread` flag and listed for the user (verification/resolution-2026-09-27/NOTICES.md).
- REPORTED to user (answered 2026-09-28: drop): GrilEtal06b — a correction (not a retraction) that withdraws the paper's headline claim.
- (default) Registry deposit codes that are not printed issue labels (SAGE `3_suppl`) are not evidence for Number; if the printed label ("3, Pt. 2") cannot be confirmed, remove Number.

## Organization authors in keys (user, 2026-09-27; key part revised 2026-09-28)
- (Rule of 2026-09-28, supersedes the first-word key part below) An organization (a fully braced author name) counts as ONE author; its key part is the letters of its successive words, concatenated until 4 letters are reached, then truncated to 4, with the capitalization as printed. User: "use as many organization 'words' as are available, until 4 letters are achieved". {R Core Team} → RCor, {U.S. Food and Drug Administration} → USFo, {RNS System in Epilepsy Study Group} → RNSS, {Centers for Disease Control and Prevention} → Cent (a first word of 4+ letters is unchanged). Letters only (digits and punctuation are skipped: {SciPy 1.0 Contributors} → SciP); a name with fewer than 4 letters in all keeps what it has. Implemented in `helpers.organization_key` (bibcheck/helpers.py), tests in tests/test_formatter_held_forms.py.
- (Rule of 2026-09-27, superseded) An organization (a fully braced author name) counts as ONE author; its key part is the first 4 letters of its first word (letters only: 'U.S.' → 'US'). Person + group → e.g. MorrRNSS11 → MorrRNS11; 'Centers for Disease Control and Prevention' → Cent23 (not ContPrev23); '{U.S. Food and Drug Administration}' → US20a/b (not FoodAdmi20a/b); Amer23a, Qwen25, Stan13, ProjEtal18 already conform.

## User answers 2026-09-28
Applied in `verification/apply-2026-09-30-final/decisions0928/` (batch-41.json, the `decisions0928` batch).

1. **SvenEtal24, co-author "N T Hoang" / "Hoang NT"** — user: spell the name out as printed in an official record. NOT CHANGED (stopped: no official record spells it out). Every official record reached prints the name as given name "Hoang", family name "NT":
   - Crossref, https://api.crossref.org/works/10.1016/j.sleep.2024.01.020: `"given": "Hoang", "family": "NT"`;
   - PubMed 38382312, https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=38382312&retmode=xml: `<LastName>Nt</LastName><ForeName>Hoang</ForeName><Initials>H</Initials>` (affiliation "Precision Health, Department of Bioengineering, Graduate School of Engineering, The University of Tokyo");
   - ORCID 0009-0008-1232-0817 (The University of Tokyo), https://pub.orcid.org/v3.0/0009-0008-1232-0817/person: `"given-names": {"value": "Hoang"}, "family-name": {"value": "NT"}`, no other names; its only link is a Google Scholar profile;
   - the ScienceDirect article page (https://www.sciencedirect.com/science/article/pii/S1389945724000200) returned 403 to curl and a CAPTCHA in the browser.
   The entry's current `N T Hoang` also disagrees with these records (they make "NT" the family name, i.e. `H NT`); left as is for the user. The entry stays needs_review.
2. **J Physiol "P" pages (BrinCrag72, J Physiol 223(1):28P--29P, 1972)** — user: "'proceedings' doesn't necessarily imply abstract ... *are* these abstracts? or papers? if only abstracts, drop." NOT CHANGED (stopped: the printed item is neither labelled an abstract nor described as refereed). Evidence (PMC page scans of the printed issue, PMC1331375 and PMC1331376, "J Physiol. 1972;223(Suppl)"):
   - the section opens (p. 1P, https://pmc.ncbi.nlm.nih.gov/articles/PMC1331375/?page=1): "PROCEEDINGS OF THE PHYSIOLOGICAL SOCIETY / IMPERIAL COLLEGE MEETING / 18-19 February 1972 / DEMONSTRATIONS"; p. 14P (https://pmc.ncbi.nlm.nih.gov/articles/PMC1331376/?page=1) starts the "COMMUNICATIONS" of the same meeting (PMC groups 14P-37P as one item titled "COMMUNICATIONS");
   - p. 28P (https://pmc.ncbi.nlm.nih.gov/articles/PMC1331376/?page=15): "The electrical activity in the motor cortex that accompanies voluntary movement / By G. S. Brindley and M. D. Craggs. M.R.C. Neurological Prostheses Unit, Institute of Psychiatry, London SE5 8AF"; p. 29P running head "PHYSIOLOGICAL SOCIETY, FEBRUARY 1972"; the item is about one page of text with a two-item reference list, followed on 29P by the next communication;
   - Wiley's version of record for the issue (https://physoc.onlinelibrary.wiley.com/toc/14697793/1972/223/1) lists "Pages: i, 1-259" and no P-pages; Crossref has no P-page item for J Physiol May-June 1972; PubMed types it "Journal Article".
   So the item is a communication given at a Physiological Society meeting, printed in the Society's Proceedings in the journal. Nothing reached calls it an "abstract", and nothing says it was refereed; the Society's pages that might describe the P-pages (physoc.org) were not found. Left for the user to decide.
3. **GrilEtal06b** (Nature Neurosci 9:1177, doi 10.1038/nn1745) — user: "DROP it". Dropped (logged in verification/key-deletions.json). The correction (doi 10.1038/nn0107-133; verification/resolution-2026-09-27/NOTICES.md: "corrigendum withdraws the headline claim (FFA nonface-selective voxels); Figs 4 and 8 invalid. Not a retraction"). By the house suffix rule the remaining GrilEtal06a (Grill-Spector, Henson & Martin, TICS 10:14-23) is now the only GrilEtal06 entry and becomes GrilEtal06.
4. **Organization author keys** — user: rename R12 to RCor12 and "use as many organization 'words' as are available, until 4 letters are achieved". Rule above ("Organization authors in keys"). R12's author fixed to `{R Core Team}` as printed (R 2.15 CITATION, https://raw.githubusercontent.com/wch/r-source/R-2-15-branch/src/library/base/inst/CITATION: `author = person("R Core Team"),`). The key check over the whole library (`bibcheck.py verify`) found exactly four keys the new rule changes: R12 → RCor12, MorrRNS11 → MorrRNSS11, US20a → USFo20a, US20b → USFo20b. All renamed (logged in verification/key-renames.json, commit `decisions0928`). Library after (`bibcheck.py crossref status cdl.bib`): 6387 entries: human_verified=31, metadata_verified=6355, needs_review=1 (SvenEtal24).
5. **ChanEtal12** (Brain Res 1453:87-101, doi 10.1016/j.brainres.2012.02.068) — user: "if the original article matches our entry, keep our entry as is", then "the actual paper is the true source". The corrigendum (doi 10.1016/j.brainres.2012.06.039, Brain Res 1470:159) is titled in Crossref 'Corrigendum to "The effects of acute exercise on cognitive performance: A meta-analytic review" [Brain Res. 1453 (2012) 87–101]'. The article's registry records all give "a meta-analysis", as the entry does: Crossref `"title": ["The effects of acute exercise on cognitive performance: A meta-analysis"]`; Europe PMC/PubMed 22480735 "The effects of acute exercise on cognitive performance: a meta-analysis."; Elsevier's article API (https://api.elsevier.com/content/article/doi/10.1016/j.brainres.2012.02.068) `<dc:title>The effects of acute exercise on cognitive performance: A meta-analysis </dc:title>`. The PRINTED article could not be read: ScienceDirect (https://www.sciencedirect.com/science/article/pii/S0006899312004003) served a CAPTCHA in the browser, and the only other copy Unpaywall lists (http://libres.uncg.edu/ir/uncg/f/J_Labban_Effects_2012.pdf) is the submitted version (Unpaywall: `submittedVersion`), not the printed one, and timed out. The corrigendum's text was not read either (its Elsevier API request returned 429). The entry is unchanged and stays metadata_verified with the notice accounted (`notices_accounted`: notice_dois ["10.1016/j.brainres.2012.06.039"]); the printed-title check is open.

**Rule (user, 2026-09-28): the printed paper is the source of truth.** When the printed paper (the publisher's PDF or full-text page, or a scan of it) and the registry metadata (Crossref, PubMed, etc.) differ, the printed paper wins. Scope (user-approved 2026-09-28): the printed paper is checked only when there is reason to doubt the registry record: a correction/erratum notice, a mismatch between sources, or a user flag. Otherwise publisher/registry metadata (Crossref etc.) stands as verification. No blanket re-read of PDFs.
