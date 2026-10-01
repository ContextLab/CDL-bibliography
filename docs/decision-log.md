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
- External APIs: asked about institutional API access, the user answered (2026-09-22 22:00 EDT): "I seem to have ProQuest access...but is there an API? I've logged into the dartmouth library website: https://search.library.dartmouth.edu/nde/home?vid=01DCL_INST:NDE01&lang=en". No later answer is recorded. Skipping ProQuest (theses use local PDFs + sign-off) was Claude's conclusion, not a user decision.

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
- Two rules first recorded in this list, "page ranges are never shortened" and "single-source
  surname changes need corroboration", were Claude's, not the user's. The user confirmed the first
  and replaced the second on 2026-09-30: see "Rules Claude adopted, then confirmed or replaced by
  the user (2026-09-30)" below.
- **Year corrections rename keys** (user, 2026-09-24 23:35 EDT: "Rename keys"): GautEtal18 → GautEtal19 and
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
  switched to the 6th edition, which names Mink and is verifiable. (Moving PsyArXiv DOIs stored
  in `volume` to `doi`, once listed in this bullet, was Claude's rule, confirmed by the user on 2026-09-30: see "Rules Claude adopted, then confirmed or replaced by the user (2026-09-30)" below.)
- **Keys always follow corrected metadata** (user, 2026-09-25 06:45 EDT: "Always rename (Recommended)"): when a verified correction
  changes the year, first author or author count, the key is renamed per the ID rule. Every
  rename is logged in `verification/key-renames.json` (old → new) so citing papers can be
  updated. (The house address form `City, {ST}`, once listed in this bullet, was not part of
  the question the user answered; the user confirmed it on 2026-09-30: see "Rules Claude adopted, then confirmed or replaced by the user (2026-09-30)" below.)
- **Proper ordinals everywhere** (user, 2026-09-25 07:36 EDT): every numeric ordinal in a text field
  (title, booktitle, journal, edition, ...) is written `N\textsuperscript{suffix}` with the
  correct suffix (`1\textsuperscript{st}`, `2\textsuperscript{nd}`, `30\textsuperscript{th}`);
  the comparator treats it as equal to "30th"/"Thirtieth" in sources.
- **Initials in publisher names without periods** (user, 2026-09-25 07:37 EDT): `W H Freeman`,
  `V H Winston` (reverses the 2B-i choice to keep "W.H.").
- **`bibcheck.py commit` gates on verification** (user, 2026-09-25 07:42 EDT): it verifies added/edited
  entries against GitHub master with `crossref verify --auto-review` and refuses to commit
  unresolved ones; it commits only the bib file (no `git commit -a`).
- **`bibcheck.py verify` checks citations too** (user, 2026-09-25 07:44 EDT): format check + citation
  verification of added/edited entries vs GitHub master + an offline library-wide status line;
  fails on any changed entry that is unresolved. `--no-citations` for format-only, `--all` for
  the whole library. `commit` shares the same check.
- **Replacements approved** (user, 2026-09-25): all 8 preprints in
  verification/apply-2026-09-25e/replacement-candidates.json are replaced by their published
  versions (LeeEtal20 → LeeEtal20a to make room for LeeEtal20b; LuriEtal20 keeps "Keilholz").
- **Sign-off of pilot verdicts** (user, 2026-09-25): entries the user marked Correct on the
  research-pilot page (or whose fixes the user approved there) that no automated source can
  verify are recorded with `crossref approve`, reviewer Jeremy Manning, bound to each entry's
  exact current text. PR #87/#88 entries were not reviewed by the user and are not included.

## Rules Claude adopted, then confirmed or replaced by the user (2026-09-30)

The 2026-09-29 attribution audit found six rules recorded as the user's. Each one was
Claude's (the model's) own generalization or fix. The user answered
[verification/2026-09-29-user-review/CONFIRM.md](../2026-09-29-user-review/CONFIRM.md) on
2026-09-30 (EDT). Their words, verbatim:

> 1. yes
> 2. yes
> 3. yes
> 4. yes
> 5. one source is sufficient; manual entry is the weakest part. notify user if mismatch is found and ask how they want to resolve it
> 6. "T Egerton" is correct -- the "." after "T" and the "..." after "Egerton" are just formatting differences
>
> yes to folder renames

### Confirmed by the user (2026-09-30)

Rules 1, 2, 3, 4 and 6 are now the user's. Each origin line below is kept as the record of
where the rule came from.

- **Proposed values must be stated by a source record** (user, 2026-09-30, question 1: "yes").
  Every proposed after-value must be stated by an authoritative source record for the
  proposal's DOI. A value carried over from the citation is never presented as source-backed.
  Origin: Claude, commit 42b524a (2026-09-24 03:07 EDT, "fixes-2026-09-24: house-form author
  proposals, source-stated issue numbers"). Claude generalized it from the user's remark "some
  \"number\" field entries don't appear in the doi link" (2026-09-24 00:20 EDT); the user's later
  spot-check notes on Hint03 ("I don't see a number field listed at the DOI address") and Murd71
  ("...Drop the number field.", 2026-09-24 18:06 EDT) concern the number field only. Affects every
  correction proposal built by `bibcheck/correction_proposals.py` (`source_records` and its
  callers); the verdicts it came from: Hint03, Murd71.
- **Page ranges are never shortened** by a correction (user, 2026-09-30, question 2: "yes").
  Origin: Claude, recorded in commit 9c301a1 (2026-09-24 21:12 EDT) and coded in 0c321c5
  (2026-09-25 00:14 EDT, `shortens_pages` in `bibcheck/correction_proposals.py`). Claude
  generalized it from one spot-check verdict, MarmEtal78: "It looks like 483--490 was correct"
  (2026-09-24 18:26 EDT; the proposal had shortened 483--490 to 483). Affects MarmEtal78, plus any
  page proposal the filter suppresses; the filter records no list of what it suppressed.
- **House address form `City, {ST}` stays** (catalogue edits that only drop the state or country
  are dropped) (user, 2026-09-30, question 3: "yes"). Origin: Claude, commit 1c1c13a (2026-09-25
  06:45 EDT), written into the same bullet as the key-rename answer. The question the user
  answered at 06:45 EDT asked only about key renames. Affects the held001 catalogue edits dropped
  by it (Tulv83, Galt83, Buzs06, OKeeNade78, and the address part of Carr93) and the city changes
  written in that form (UndeShul60 "Chicago, {IL}", TulvDona72 "New York, {NY}"). The research
  post-check (`verification/research-2026-09-25/postcheck.py`) normalizes US addresses to the
  same form.
- **PsyArXiv DOIs stored in `volume` move to `doi`** (user, 2026-09-30, question 4: "yes").
  Origin: Claude, commit 4cb7741 (2026-09-25 00:32 EDT), bundled into the "Pilot follow-up
  decisions (user, 2026-09-25)" bullet. It came from the researcher's note on ZimaEtal23
  (research-pilot `followup.json`: "Three other cdl.bib entries ... also store PsyArXiv DOIs in
  volume; the same fix applies"). Affects ZimaEtal23, GralFinn21, LuriEtal18 and NussEtal18. The
  last three were later replaced by their published versions under the user's "Replace all 8".
- **Aust14's publisher is "T Egerton"** (user, 2026-09-30, question 6: '"T Egerton" is correct
  -- the "." after "T" and the "..." after "Egerton" are just formatting differences').
  The Library of Congress record prints "Printed for T. Egerton, Military Library, Whitehall".
  Origin: Claude's agent instruction of 2026-09-25 11:10 EDT ("Also fix Aust14 publisher
  'Eagerton' -> the real firm (Egerton)"), applied in commit 2179d34 (2026-09-25 13:01 EDT,
  prfix001). The code comment said "(user: ...)", but no user record asked for it until this
  answer. Affects Aust14.

### Replaced by the user's rule (2026-09-30)

- **Surname mismatches go to the user** (user, 2026-09-30, question 5: "one source is
  sufficient; manual entry is the weakest part. notify user if mismatch is found and ask how
  they want to resolve it"). One authoritative source record is enough to verify an author's
  surname it agrees with; no second source is needed. When the cited surname and a source's
  surname disagree, the checker neither keeps the cited spelling nor applies the source's on
  its own: the entry stays `needs_review` with an issue that names both spellings and the
  source, and the user decides. Implemented in
  [apply-2026-09-30-surnames](../apply-2026-09-30-surnames/README.md): the auto-review rule that
  let PubMed and library consensus overrule a Crossref surname (`registry-surname-typo`) now names
  the mismatch instead, every surname-changing correction is held (`surname_change_hold`), and the
  research post-check holds every respelling. The open questions are in
  [verification/2026-09-30-user-review/SURNAMES.md](../2026-09-30-user-review/SURNAMES.md).
- The rule it replaces, for the record: **single-source surname changes need corroboration** (a
  second source, or held when other cdl.bib entries spell the same author the cited way).
  Origin: Claude, recorded in commit 9c301a1 (2026-09-24 21:12 EDT) and coded in 0c321c5
  (2026-09-25 00:14 EDT, `surname_change_hold`), after Claude's own risky001 batch applied
  Crossref's "Kounois" to MeyeEtal88. No user record stated it. Affected MeyeEtal88 (reverted,
  apply-2026-09-25 `revert-kounios`) and RuggEtal96 (held in held001, apply-2026-09-25c).

### Folder renames confirmed (2026-09-30)

- The user's "yes to folder renames" (2026-09-30) confirms the renames of the eight misdated
  `apply-*` folders to their creation dates (commit 856d637; table in
  [verification/README.md](../README.md#renamed-apply-folders-2026-09-29)).

### Other corrections from the 2026-09-29 audit

- **Dates.** Seven decisions were stamped with the wrong day. The times above are now the answer
  times from the session record in EDT (UTC-4): year-correction key renames 2026-09-24 23:35;
  keys follow corrected metadata 2026-09-25 06:45; ordinals 07:36; publisher initials 07:37; the
  commit gate 07:42; `verify` checks citations 07:44 (all 2026-09-25). The proceedings-name rule
  ("omit year in conference names; it's redundant with the year field", research-pilot page,
  XiaoEtal10, 2026-09-25 00:01 EDT) is dated "user decision 2026-09-26" only in the message of
  commit 23cc902, which git history keeps; the commit itself is dated 2026-09-25 07:52 EDT.
- **Palm78** was not "kept unchanged (user)". The user's page note was "again, add DOI" (verdict
  "wrong", 2026-09-25 00:06 EDT). Keeping it unchanged was Claude's instruction to an agent
  (2026-09-25 11:10 EDT). Its approval was revoked; the DOI question is in
  [verification/2026-09-29-user-review/REVIEW.md](../2026-09-29-user-review/REVIEW.md).
- **Spot-check size.** The "~50 entries" design (verification/spotcheck-2026-09-23) was Claude's.
  The user said "i could maybe do 100 (upper limit)" (2026-09-22 22:04 EDT) and chose "10 per
  class (Recommended)" (22:10 EDT).
- **Sign-offs.** Twelve approvals recorded as the user's sign-off were revoked on 2026-09-29 (the
  user chose "Revoke, I'll review"); see `verification/revocations.jsonl`.

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
- **Duplicates:** the user marked 8 of the 9 keepers "correct". For KahaEtal08b→KahaEtal08a the verdict was "unsure", with the note "drop the \"a\" at the end of the key if this is the only KahaEtal08" (crosswave page, 2026-09-26 14:15 EDT; `verification/research-2026-09-25/crosswave/decisions/dup-KahaEtal08b-KahaEtal08a.json`). The earlier wording, "all 9 keepers approved; KahaEtal08b→KahaEtal08a approved", overstated this.

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
- (Rule of 2026-09-30, refines the rule of 2026-09-28) A dotted abbreviation in the organization's name counts as the words it stands for. User: "'U.S.' decomposes to 'United States' so the first 4 letters are 'Unit'". The expansions are a short explicit table, `helpers.ORGANIZATION_ABBREVIATIONS` (U.S. → United States, U.S.A. → United States of America, U.K. → United Kingdom, U.N. → United Nations); an undotted or unlisted form keeps its letters as printed. {U.S. Food and Drug Administration} → Unit. The key check over the library found exactly two keys the rule changes: USFo20a → Unit20a, USFo20b → Unit20b (logged in verification/key-renames.json, commit `orgkey0930`).
- (Rule of 2026-09-28, supersedes the first-word key part below) An organization (a fully braced author name) counts as ONE author; its key part is the letters of its successive words, concatenated until 4 letters are reached, then truncated to 4, with the capitalization as printed. User: "use as many organization 'words' as are available, until 4 letters are achieved". {R Core Team} → RCor, {U.S. Food and Drug Administration} → USFo, {RNS System in Epilepsy Study Group} → RNSS, {Centers for Disease Control and Prevention} → Cent (a first word of 4+ letters is unchanged). Letters only (digits and punctuation are skipped: {SciPy 1.0 Contributors} → SciP); a name with fewer than 4 letters in all keeps what it has. Implemented in `helpers.organization_key` (bibcheck/helpers.py), tests in tests/test_formatter_held_forms.py.
- (Rule of 2026-09-27, superseded) An organization (a fully braced author name) counts as ONE author; its key part is the first 4 letters of its first word (letters only: 'U.S.' → 'US'). Person + group → e.g. MorrRNSS11 → MorrRNS11; 'Centers for Disease Control and Prevention' → Cent23 (not ContPrev23); '{U.S. Food and Drug Administration}' → US20a/b (not FoodAdmi20a/b); Amer23a, Qwen25, Stan13, ProjEtal18 already conform.

## User answers 2026-09-28
Applied in `verification/apply-2026-09-27b-final/decisions0928/` (batch-41.json, the `decisions0928` batch).

1. **SvenEtal24, co-author "N T Hoang" / "Hoang NT"** — user: spell the name out as printed in an official record. Stopped (no official record spells it out), then DROPPED under the ambiguity rule below (batch 42). Every official record reached prints the name as given name "Hoang", family name "NT":
   - Crossref, https://api.crossref.org/works/10.1016/j.sleep.2024.01.020: `"given": "Hoang", "family": "NT"`;
   - PubMed 38382312, https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=38382312&retmode=xml: `<LastName>Nt</LastName><ForeName>Hoang</ForeName><Initials>H</Initials>` (affiliation "Precision Health, Department of Bioengineering, Graduate School of Engineering, The University of Tokyo");
   - ORCID 0009-0008-1232-0817 (The University of Tokyo), https://pub.orcid.org/v3.0/0009-0008-1232-0817/person: `"given-names": {"value": "Hoang"}, "family-name": {"value": "NT"}`, no other names; its only link is a Google Scholar profile;
   - the ScienceDirect article page (https://www.sciencedirect.com/science/article/pii/S1389945724000200) returned 403 to curl and a CAPTCHA in the browser.
   The entry's current `N T Hoang` also disagrees with these records (they make "NT" the family name, i.e. `H NT`); left as is for the user. The entry stays needs_review.
2. **J Physiol "P" pages (BrinCrag72, J Physiol 223(1):28P--29P, 1972)** — user: "'proceedings' doesn't necessarily imply abstract ... *are* these abstracts? or papers? if only abstracts, drop." Stopped (the printed item is neither labelled an abstract nor described as refereed), then DROPPED under the ambiguity rule below (batch 42). Evidence (PMC page scans of the printed issue, PMC1331375 and PMC1331376, "J Physiol. 1972;223(Suppl)"):
   - the section opens (p. 1P, https://pmc.ncbi.nlm.nih.gov/articles/PMC1331375/?page=1): "PROCEEDINGS OF THE PHYSIOLOGICAL SOCIETY / IMPERIAL COLLEGE MEETING / 18-19 February 1972 / DEMONSTRATIONS"; p. 14P (https://pmc.ncbi.nlm.nih.gov/articles/PMC1331376/?page=1) starts the "COMMUNICATIONS" of the same meeting (PMC groups 14P-37P as one item titled "COMMUNICATIONS");
   - p. 28P (https://pmc.ncbi.nlm.nih.gov/articles/PMC1331376/?page=15): "The electrical activity in the motor cortex that accompanies voluntary movement / By G. S. Brindley and M. D. Craggs. M.R.C. Neurological Prostheses Unit, Institute of Psychiatry, London SE5 8AF"; p. 29P running head "PHYSIOLOGICAL SOCIETY, FEBRUARY 1972"; the item is about one page of text with a two-item reference list, followed on 29P by the next communication;
   - Wiley's version of record for the issue (https://physoc.onlinelibrary.wiley.com/toc/14697793/1972/223/1) lists "Pages: i, 1-259" and no P-pages; Crossref has no P-page item for J Physiol May-June 1972; PubMed types it "Journal Article".
   So the item is a communication given at a Physiological Society meeting, printed in the Society's Proceedings in the journal. Nothing reached calls it an "abstract", and nothing says it was refereed; the Society's pages that might describe the P-pages (physoc.org) were not found. Left for the user to decide.
3. **GrilEtal06b** (Nature Neurosci 9:1177, doi 10.1038/nn1745) — user (2026-09-28 07:29 EDT), replying to item 3: "3. drop". (An earlier version quoted "DROP it"; those were Claude's words in an agent instruction, not the user's.) Dropped (logged in verification/key-deletions.json). The correction (doi 10.1038/nn0107-133; verification/resolution-2026-09-27/NOTICES.md: "corrigendum withdraws the headline claim (FFA nonface-selective voxels); Figs 4 and 8 invalid. Not a retraction"). By the house suffix rule the remaining GrilEtal06a (Grill-Spector, Henson & Martin, TICS 10:14-23) is now the only GrilEtal06 entry and becomes GrilEtal06.
4. **Organization author keys** — user: rename R12 to RCor12 and "use as many organization 'words' as are available, until 4 letters are achieved". Rule above ("Organization authors in keys"). R12's author fixed to `{R Core Team}` as printed (R 2.15 CITATION, https://raw.githubusercontent.com/wch/r-source/R-2-15-branch/src/library/base/inst/CITATION: `author = person("R Core Team"),`). The key check over the whole library (`bibcheck.py verify`) found exactly four keys the new rule changes: R12 → RCor12, MorrRNS11 → MorrRNSS11, US20a → USFo20a, US20b → USFo20b. All renamed (logged in verification/key-renames.json, commit `decisions0928`). Library after (`bibcheck.py crossref status cdl.bib`): 6387 entries: human_verified=31, metadata_verified=6355, needs_review=1 (SvenEtal24).
5. **ChanEtal12** (Brain Res 1453:87-101, doi 10.1016/j.brainres.2012.02.068) — user: "if the original article matches our entry, keep our entry as is", then "the actual paper is the true source". The corrigendum (doi 10.1016/j.brainres.2012.06.039, Brain Res 1470:159) is titled in Crossref 'Corrigendum to "The effects of acute exercise on cognitive performance: A meta-analytic review" [Brain Res. 1453 (2012) 87–101]'. The article's registry records all give "a meta-analysis", as the entry does: Crossref `"title": ["The effects of acute exercise on cognitive performance: A meta-analysis"]`; Europe PMC/PubMed 22480735 "The effects of acute exercise on cognitive performance: a meta-analysis."; Elsevier's article API (https://api.elsevier.com/content/article/doi/10.1016/j.brainres.2012.02.068) `<dc:title>The effects of acute exercise on cognitive performance: A meta-analysis </dc:title>`. The PRINTED article could not be read: ScienceDirect (https://www.sciencedirect.com/science/article/pii/S0006899312004003) served a CAPTCHA in the browser, and the only other copy Unpaywall lists (http://libres.uncg.edu/ir/uncg/f/J_Labban_Effects_2012.pdf) is the submitted version (Unpaywall: `submittedVersion`), not the printed one, and timed out. The corrigendum's text was not read either (its Elsevier API request returned 429). The entry was first left unchanged (metadata_verified, notice accounted); it was then DROPPED under the ambiguity rule below (batch 42): a corrigendum exists, and under the printed-paper rule the printed article decides, but neither it nor the corrigendum could be read.

**Rule (user, 2026-09-28): the printed paper is the source of truth.** When the printed paper (the publisher's PDF or full-text page, or a scan of it) and the registry metadata (Crossref, PubMed, etc.) differ, the printed paper wins. Scope (user-approved 2026-09-28): the printed paper is checked only when there is reason to doubt the registry record: a correction/erratum notice, a mismatch between sources, or a user flag. Otherwise publisher/registry metadata (Crossref etc.) stands as verification. No blanket re-read of PDFs.

**Rule (user, 2026-09-28): "ok, if ambiguous, drop-- we can always add back if needed later".** If a question stays ambiguous after research (it can't be settled from an official or printed source), drop the entry; it can be re-added later. Applied to BrinCrag72, SvenEtal24 and ChanEtal12 (`verification/apply-2026-09-27b-final/decisions0928b/`, batch-42.json; logged in verification/key-deletions.json). No suffixed siblings existed, so no key changed. MorrRNSS11 keeps its key under the organization rule.

## User answers 2026-09-30 (review page)

The user answered the review page https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM (database
collection `review0930`; the page, its template, its build script and the notes-audit input are
in [verification/2026-09-30-user-review/page/](../2026-09-30-user-review/page/)). The answer
documents were read with the ArtifactData tool on 2026-09-30 (15:25 UTC) and are copied in
[verification/apply-2026-09-30b-answers/answers/](../apply-2026-09-30b-answers/answers/). The
user's message on sending them: "i've answered all questions". Sections A, B and D are applied
here (batch `answers0930b`,
[apply-2026-09-30b-answers](../apply-2026-09-30b-answers/README.md)); section C (surnames) is
still being answered and is not applied. Times are the documents' `updatedAt` (UTC) and EDT
(UTC-4).

**A. Approved entries changed by the brace cleanup (4cdc644).** Question: "The brace cleanup
changed this approved entry (braces only). Approve the new text?" Each answered "approve"
(option "Approve"), no note. Recorded with `crossref approve` on the entry's current fingerprint,
reviewer "Jeremy Manning", source "review page https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM,
collection review0930, doc brace-KEY, answered UTC-time", note "User approved the
post-brace-cleanup text on the 2026-09-30 review page (choice: approve)."

| Entry | Doc | Answered (UTC) | EDT |
|-|-|-|-|
| Bart32 | brace-Bart32 | 2026-09-30T14:38:48.029Z | 10:38:48 |
| KahaEtal24 | brace-KahaEtal24 | 2026-09-30T14:38:52.661Z | 10:38:52 |
| Mink15 | brace-Mink15 | 2026-09-30T14:38:57.195Z | 10:38:57 |
| Youn61 | brace-Youn61 | 2026-09-30T14:38:59.862Z | 10:38:59 |

Mink15's earlier approval (fingerprint v2:0c83ad54..., before the brace cleanup) was revoked on
2026-09-29; the new approval is on the current fingerprint (v2:91136b00...) with a new note, so the
revocation does not touch it, and the old approval still cannot be replayed (refused: "Entry
changed since review").

**B. Page notes that weren't followed, or that the user left open.**

| Entry | Doc | Answer | Answered (UTC) | EDT | Applied |
|-|-|-|-|-|-|
| CronEtal94 | note-CronEtal94 | "drop" ("Confirm the drop") | 2026-09-30T14:39:09.996Z | 10:39:09 | stays deleted; `confirmed_by` (doc and time) added to its row in verification/key-deletions.json |
| DougPeuc73 | note-DougPeuc73 | "keep" ("Keep 'The Canadian Cartographer' (name printed in 1973)") | 2026-09-30T14:39:12.229Z | 10:39:12 | no change |
| Mann06 | note-Mann06 | "keep" ("Keep @mastersthesis with Type = {Senior thesis}") | 2026-09-30T14:39:15.613Z | 10:39:15 | no change |
| Hint03 | note-Hint03 | "keep" ("Keep Number = 1 (Crossref states issue 1)") | 2026-09-30T14:39:05.912Z | 10:39:05 | Number = {1} kept (Crossref: "issue":"1") |
| Murd71 | note-Murd71 | "keep" ("Keep Number = 4 (Crossref states issue 4)") | 2026-09-30T14:39:07.379Z | 10:39:07 | Number = {4} kept (Crossref: "issue":"4") |
| KahaEtal08b | note-KahaEtal08b | "change" ("Something else (say what)") | 2026-09-30T14:39:59.669Z | 10:39:59 | keys swapped (below) |

KahaEtal08b, the user's note verbatim: "Use KahaEta08a for \"Putting short-term memory into
context:...\" and KahaEtal08b for \"Associative processes in episodic memory\"". Interpretation
(the orchestrating session's, stated to the user): swap the two keys. The Psychological Review
reply (doi 10.1037/a0013724, until now KahaEtal08b) is now **KahaEtal08a**; the chapter (doi
10.1016/b978-012370509-9.00185-6, until now KahaEtal08a) is now **KahaEtal08b**. "KahaEta08a" in
the note is read as KahaEtal08a. The chapter keeps its printed title "Associative retrieval
processes in episodic memory": the user's wording identified the chapter, and the user was told
the title would stay as printed. Logged in verification/key-renames.json (commit `answers0930b`,
with the user's note and the doc time) as three renames through a temporary key
(KahaEtal08a → KahaEtal08-swap-2026-09-30, KahaEtal08b → KahaEtal08a, KahaEtal08-swap-2026-09-30
→ KahaEtal08b), so that `research_route.rename_walk`, which follows the log in order, maps each
work's research evidence to its new key. Content fingerprints are key-independent; both entries
kept `metadata_verified` with the same accepted record (reply: Crossref 10.1037/a0013724; chapter:
research evidence, 10.1016/b978-012370509-9.00185-6).

**D. Resolved under the user's rule.** Each answered "ok" (option "Fine"), no note.

| Entry | Doc | Answered (UTC) | EDT | The user's page request | Applied |
|-|-|-|-|-|-|
| Hook69 | resolved-Hook69 | 2026-09-30T14:40:01.051Z | 10:40:01 | "title should be \"The posthumous works of Robert Hooke\"" | `crossref approve` |
| KahaMill13 | resolved-KahaMill13 | 2026-09-30T14:40:02.634Z | 10:40:02 | "add doi too" | `crossref approve` |
| Palm78 | resolved-Palm78 | 2026-09-30T14:40:04.267Z | 10:40:04 | "again, add DOI" | recorded as resolved; already `metadata_verified` (research route), no write |
| ScotEtal07 | resolved-ScotEtal07 | 2026-09-30T14:40:07.101Z | 10:40:07 | "this is a book; shouldn't be a pages field" | `crossref approve` |

The three approvals: reviewer "Jeremy Manning", source "review page
https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM, collection review0930, doc resolved-KEY,
answered UTC-time", note "Resolved under the user's 2026-09-30 rule ('if you followed what i
asked then mark as resolved'); the user's page request (“request”) was followed; confirmed 'ok'
on the 2026-09-30 review page." The rule is the user's own message in the orchestrating session
(transcript 0ff7c242, 2026-09-30T13:42:04Z = 09:42:04 EDT), verbatim: "1. if I asked to add a
DOI and the DOI doesn't exist, mark resolved. for other notes/requests, if you followed what i
asked then mark as resolved and otherwise flag for my re-review." The page's own summary of the rule (section D
heading): "Your rule (2026-09-30): if your request was followed, it's resolved; a DOI that
doesn't exist counts as resolved."

**Checker changes made with this batch (Claude's, not the user's decisions).** Two name-parsing
defects found by the surname scan were fixed (a tilde accent outside braces, `Pi\~{n}a`, split
the surname; `\aa` was rejected); no entry's status changes. Replaying a revoked approval as
the revocation ledger shows it was accepted, because commit 856d637 had edited the ledger's
approval text (ScotEtal07's replay was accepted during this batch and then re-read as revoked);
a revocation now revokes the approval text it carries as well as its recorded digest. The
research post-check follows key-renames.json in log order, so the key swap does not send
KahaEtal08c (the reply) to the chapter. Details:
[apply-2026-09-30b-answers](../apply-2026-09-30b-answers/README.md). Library after the batch:
`6384 entries: human_verified=23, metadata_verified=6353, needs_review=8`.


## User surname decisions 2026-09-30

The user's rule (2026-09-30): "one source is sufficient; manual entry is the weakest part. notify
user if mismatch is found and ask how they want to resolve it". The 137 mismatches were put to
the user on the review page https://claude.ai/artifact/J9gYrxEMWk4AwQcExiznEM (collection
`review0930`). The answer documents were read with the ArtifactData tool on 2026-09-30 and are
copied in [verification/apply-2026-09-30c-surnames/answers/](../apply-2026-09-30c-surnames/answers/);
every mismatch's decision is in
[decisions.json](../apply-2026-09-30c-surnames/decisions.json). Applied as batch
`surnames0930c` ([apply-2026-09-30c-surnames](../apply-2026-09-30c-surnames/README.md)). Times
are the documents' `updatedAt` (UTC) and EDT (UTC-4). Sections E and F had no documents: their
rows were settled by the printed bylines (below) or asked again in section I.

| Doc | Section | Choice | Note | Answered (UTC) | EDT |
|-|-|-|-|-|-|
| surname-AndeEtal66-2 | C | entry |  | 2026-09-30T15:56:04.244Z | 11:56:04 |
| surname-AndeEtal66-3 | C | source |  | 2026-09-30T15:56:51.933Z | 11:56:51 |
| surname-BahrPhel87-2 | C | entry |  | 2026-09-30T15:57:38.288Z | 11:57:38 |
| surname-Buzs98-1 | C | entry |  | 2026-09-30T15:58:16.959Z | 11:58:16 |
| surname-FreeEtal03b-3 | C | entry |  | 2026-09-30T15:58:30.178Z | 11:58:30 |
| surname-IshiEtal75-3 | C | source |  | 2026-09-30T15:58:53.264Z | 11:58:53 |
| surname-KatzEtal89-3 | C | source |  | 2026-09-30T15:59:39.969Z | 11:59:39 |
| surname-KimbEtal08-1 | C | entry |  | 2026-09-30T16:00:10.406Z | 12:00:10 |
| surname-LuriEtal20-6 | C | entry |  | 2026-09-30T16:01:12.263Z | 12:01:12 |
| surname-Madi71-1 | C | entry |  | 2026-09-30T16:01:59.601Z | 12:01:59 |
| surname-MallEtal97-3 | C | source |  | 2026-09-30T16:02:28.655Z | 12:02:28 |
| surname-MeyeEtal88-4 | C | source |  | 2026-09-30T16:03:18.677Z | 12:03:18 |
| surname-NewmBuck62-2 | C | entry |  | 2026-09-30T16:04:31.836Z | 12:04:31 |
| surname-RebeEtal02-3 | C | source |  | 2026-09-30T16:05:44.861Z | 12:05:44 |
| surname-SlamFevr83-1 | C | entry |  | 2026-09-30T16:06:21.899Z | 12:06:21 |
| surname-TulvHast72-1 | C | entry |  | 2026-09-30T16:06:34.134Z | 12:06:34 |
| surname-WaszWalt83-1 | C | entry |  | 2026-09-30T16:07:27.056Z | 12:07:27 |
| surname-WatkPeyn83-2 | C | other | should actually be Peyn\dot{i}rc\dot{i}o\u{g}lu | 2026-09-30T16:09:29.471Z | 12:09:29 |
| surname-Wick69-1 | C | entry |  | 2026-09-30T16:10:02.024Z | 12:10:02 |
| surname-KragEtal19-9 | C | source |  | 2026-09-30T16:11:08.415Z | 12:11:08 |
| surname-LopeEtal73-4 | C | source |  | 2026-09-30T16:11:11.883Z | 12:11:11 |
| surname-dBakEtal08-1 | C | source |  | 2026-09-30T16:11:57.821Z | 12:11:57 |
| surname-group-format | C | show | Unify the spellings | 2026-09-30T16:13:42.400Z | 12:13:42 |
| surname-group-longer | C | except | Vom{S}aal should be "{vom Saal}" | 2026-09-30T16:16:45.772Z | 12:16:45 |
| surname-group-shorter | C | show |  | 2026-09-30T16:18:59.037Z | 12:18:59 |
| surname-group-corrupt | C | show |  | 2026-09-30T16:19:36.024Z | 12:19:36 |
| typo-RebeEtal02-3 | H | correct |  | 2026-09-30T17:22:08.184Z | 13:22:08 |
| manual-recheck-IshiEtal75-3 | I | source |  | 2026-09-30T17:22:34.437Z | 13:22:34 |
| manual-surname1-KarpRoed07-2 | I | entry |  | 2026-09-30T17:22:50.239Z | 13:22:50 |
| manual-surname1-BuzsEtal83-2 | I | entry |  | 2026-09-30T17:23:02.558Z | 13:23:02 |
| manual-surname1-GallRoed02-2 | I | entry |  | 2026-09-30T17:23:08.025Z | 13:23:08 |
| manual-surname1-LopeEtal73-1 | I | other | "{Lopes da Silva}" | 2026-09-30T17:23:41.745Z | 13:23:41 |
| manual-surname1-SpinEtal88-2 | I | entry |  | 2026-09-30T17:24:03.447Z | 13:24:03 |
| manual-surname1-VieiEtal03-2 | I | entry |  | 2026-09-30T17:24:17.215Z | 13:24:17 |
| manual-surname1-vandEtal11-1 | I | entry |  | 2026-09-30T17:24:27.233Z | 13:24:27 |
| manual-surname1-ConwEtal00-4 | I | source |  | 2026-09-30T17:24:44.151Z | 13:24:44 |
| manual-surname1-MillEtal07c-2 | I | source |  | 2026-09-30T17:24:59.253Z | 13:24:59 |
| manual-surname1-MillEtal07d-5 | I | source |  | 2026-09-30T17:25:05.487Z | 13:25:05 |
| manual-surname1-PennEtal94-3 | I | other | "{Lopes da Silva}" | 2026-09-30T17:25:23.111Z | 13:25:23 |
| manual-surname1-SchaEtal11-3 | I | source |  | 2026-09-30T17:25:44.691Z | 13:25:44 |
| manual-surname1-StJaEtal12-1 | I | source |  | 2026-09-30T17:25:50.224Z | 13:25:50 |
| manual-surname1-VanSEtal07-1 | I | entry |  | 2026-09-30T17:25:56.459Z | 13:25:56 |
| manual-surname1-VanSEtal07-3 | I | entry |  | 2026-09-30T17:26:14.927Z | 13:26:14 |
| manual-surname1-BrisEtal02-3 | I | entry |  | 2026-09-30T17:26:54.181Z | 13:26:54 |
| manual-surname1-NuneEtal87-1 | I | entry |  | 2026-09-30T17:27:47.604Z | 13:27:47 |
| manual-surname1-NuneEtal87-2 | I | entry |  | 2026-09-30T17:27:58.704Z | 13:27:58 |
| manual-surname1-SlawKasi95-1 | I | entry |  | 2026-09-30T17:28:09.105Z | 13:28:09 |
| rule-unify | G | per-paper |  | 2026-09-30T17:28:37.258Z | 13:28:37 |

**Rule answers recorded here.**

- **Per-paper (user, doc rule-unify, "per-paper", 2026-09-30T17:28:37.258Z = 13:28:37 EDT).**
  Question: the same person's name is printed differently in different papers; option chosen:
  "Each entry follows its own printed paper" (not "One spelling per person everywhere"). Applied:
  FreuEtal09 author 6 "J Klosterkoetter", LatiEtal10 author 7 "F Dagata", NadeEtal00 author 3
  "J E {Le Doux}", each as its printed byline shows (printed.json). Other entries of the same
  people are not changed.
- **The printed paper wins** (user rule 2026-09-28, above) settled 43 rows whose printed byline
  equals the entry (printed.json class PRINTED=ENTRY), including four where the user had first
  picked Crossref's spelling in section C: AndeEtal66#3 Hamberger, KatzEtal89#3 Kong,
  MallEtal97#3 Sch{\"o}lkopf, MeyeEtal88#4 Kounios.
- **Gitelman exception (user, doc typo-RebeEtal02-3, "correct", 2026-09-30T17:22:08.184Z =
  13:22:08 EDT).** The Journal of Neuroscience printed author 3 as "Darren R. Gitleman" (p. 9541,
  https://www.jneurosci.org/content/22/21/9541.full.pdf); the user chose the correct spelling
  "Gitelman" over the printed typo. A user-approved exception to the as-printed rule; the entry
  is unchanged.
- **Name suffixes.** The six rows whose source adds a suffix (EngeEtal10#6, GomeEtal96#3,
  IyyeEtal15#4, PollGero68#2, Roed08#1, Warr98#1) keep the entry under the user's rule in
  "Spot-check completed (2026-09-24/25) and resulting decisions" above: "No name suffixes (Jr, Sr,
  II, III, IV): never added; the 27 existing ones are stripped; the comparator ignores suffixes."
- **"St. Jacques"** (SchaEtal11#3, StJaEtal12#1, answered "source"): in house form (periods
  stripped) this is "{St Jacques}", the entry's spelling; no edit.
- **The three rows the page left open (user, 2026-09-30, relayed verbatim by the orchestrating
  session; message time not recorded here):** "1. ConwEtal00 had an apostrophe, not an accent /
  2. denNijs is printed as one word in the example pub". Applied with the user's section I
  "source" answers: ConwEtal00 author 4 "M Racsma'ny" (ASCII apostrophe), MillEtal07c author 2
  and MillEtal07d author 5 "M denNijs".

**Changes (cdl.bib).** KragEtal19 #9 "L F Barrett" → "L {Feldman Barrett}"; LopeEtal73 #4
"W S {van Leeuwen}" → "W {Storm van Leeuwen}" and #1 "F H {Lopes Da Silva}" → "F H {Lopes da
Silva}"; PennEtal94 #3 → "F H {Lopes da Silva}"; dBakEtal08 #1 "R S J {d Baker}" → "R S J {d}
Baker"; MurdVomS67 #2 "W {Vom {S}aal}" → "W {vom Saal}", key renamed **MurdVomS67 → MurdvomS67**
(helpers.authors2key; logged in verification/key-renames.json, commit `surnames0930c`, with the
user's note "Vom{S}aal should be \"{vom Saal}\"" from doc surname-group-longer, "except",
2026-09-30T16:16:45.772Z); IshiEtal75 #3 "N Yoshimasu" → "N Yoshimasa"; FreuEtal09, LatiEtal10,
NadeEtal00, ConwEtal00, MillEtal07c, MillEtal07d as above. Everything else is kept.

**Not applied as written, for the user to decide** (evidence in the batch README):
- dBakEtal08: "R S J d Baker" renders in BibTeX as "d Baker" (the lowercase d is read as a
  particle), so the author is "R S J {d} Baker", which renders "Baker, R. S. J. d." as Crossref
  has it. The key stays dBakEtal08 (authors2key reads "d" as a surname prefix either way).
- WatkPeyn83: the user's "Peyn\dot{i}rc\dot{i}o\u{g}lu" was not applied. `\dot` is a
  math-mode accent; in text mode pdflatex stops ("! Missing $ inserted."), so every paper citing
  the entry would fail to build. The entry keeps "Z F Peynircio\u{g}lu" and stays verified.
- LatiEtal10: its published erratum (10.1007/s00426-016-0761-6, Psychol Res 80(4):727, 2016)
  corrects "Dagata" to "D'Agata" (PubMed: "Dagata, Federico [corrected to D’Agata, Federico]").
  The per-paper spelling "Dagata" is applied as the user chose, but the entry is `needs_review`
  on that correction notice until the user decides between the printed article and its
  correction.
- FreuEtal09: `needs_review` on its erratum (10.1001/archneurol.2011.75), which corrects a
  Methods sentence, not the byline; earlier adjudicated (research wave 2) as no change to the
  citation, but that approval was bound to the old text.

**Approvals** (`bibcheck.py crossref approve`, reviewer "Jeremy Manning", current fingerprint;
source: the page, collection, doc id(s), choice and answer time, or for entries settled by the
printed byline alone the page and the 2026-09-28 rule; note: the chosen spelling and the printed
evidence): ConwEtal00, dBakEtal08, LopeEtal73, PennEtal94, MeyeEtal88, BragEtal99, RobeEtal99,
NoldEtal98, SchaEtal11, StJaEtal08, StJaEtal12, StJaScha13.
Library after the batch (`bibcheck.py crossref status cdl.bib`): `6384 entries: human_verified=35, metadata_verified=6347, needs_review=2`.

**Follow-up (user, 2026-09-30; batch `followup0930d`,
[apply-2026-09-30d-followup](../apply-2026-09-30d-followup/README.md)).** The orchestrating
session asked: (1) keep WatkPeyn83 as Peynircio\u{g}lu, since `\dot` is a math-only accent and
plain i is the dotted i? (2) use "D'Agata" per the erratum 10.1007/s00426-016-0761-6? (3)
re-approve FreuEtal09, whose erratum concerns only a Methods sentence? The user's answer,
verbatim (relayed by the orchestrating session; message time not recorded here): "1. yes / 2. use
D'Agata / 3. Re-confirm". Applied: (1) WatkPeyn83 unchanged ("Z F Peynircio\u{g}lu",
`metadata_verified`); the hold is withdrawn. (2) LatiEtal10 author 7 "F Dagata" → "F D'Agata" per
the publisher's erratum (Crossref title "Erratum to: Route and survey processing of topographical
memory during navigation", update-to 10.1007/s00426-010-0276-5; correction text "the name of the
seventh author was incorrectly published as Federico Dagata. However, the correct name should
read as Federico D'Agata."; PubMed 20174930 "Dagata, Federico [corrected to D’Agata,
Federico]"); this overrides the per-paper spelling for this entry because the publisher corrected
the printed byline. It verifies again on its earlier research evidence. (3) FreuEtal09: `crossref
approve`, reviewer "Jeremy Manning", note "User re-confirmed 2026-09-30; the erratum
(10.1001/archneurol.2011.75) corrects a Methods sentence, not the citation." Library after:
`6384 entries: human_verified=36, metadata_verified=6348`.
