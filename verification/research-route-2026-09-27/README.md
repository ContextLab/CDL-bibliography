# Research route (2026-09-27): approvals from the research waves' evidence

`bibcheck/research_route.py` records the entries that the research waves verified field by field as
`metadata_verified` (`accepted_source = research-evidence`). The backfill command is:

    .venv/bin/python bibcheck.py crossref research-approve cdl.bib [--dry-run] [--output FILE] [--keys FILE]

It reads saved files only and makes no network request. It writes review rows through `Cache.put`, and a
repeat run writes nothing. Evidence files with uncommitted changes (`git status` of the research folders)
are left out and listed. Tests: `tests/test_research_route.py` (real entries, rows and saved bodies frozen
under `tests/fixtures/research_route/` by its `build.py`).

## Evidence read

- Researcher rows: `research-pilot-2026-09-24/batch-*.json`, `research-2026-09-25/wave*/batch-*.json`.
- The pilot's applied changes: `pilot-proposals.json`, `followup.json`.
- Each wave's `merged.json` (post-check final values with their evidence, `needs_user`, `remove_entry`,
  field removals) and `review.json` (reviewer values).
- The user's answers: `wave1/decisions/*.json` and `crosswave/applied-decisions.json`.
- Resolution batches `resolution-2026-09-26/batch-*.json` (01-39 since the update below; `set`, `withdraw`,
  `remove`, `drop`). A file that is not valid JSON raises; leave it out with `exclude`.
- The notice classification `resolution-2026-09-27/notices-classified.json` (update below).
- Manual research `research-2026-09-26-manual/proposals.json`.
- `key-renames.json` is followed in log order. A key in `key-deletions.json` is never followed: its rows
  describe a deleted work, and the key may now name another one (KahaEtal08b: the wave-8 row and the
  batch-19 `drop` are about the deleted duplicate, the current KahaEtal08b is the former KahaEtal08c).
- Quote bodies: validate.py's cache `.bibcheck/research-pilot/<sha256(url)>.txt`. Each quote is searched
  with validate.py's normalisation (`norm`, `hyphen_joined`), and a value is tested with its
  `value_supported`. The body's sha256 is stored with every quote.

## Approval rule

An entry is approved only when all of these hold:

1. Gates. A research row exists (or a resolution batch decided `apply`/`keep` for an entry no wave
   queued). Its verdict is `verified` or `correction`, unless a resolution decision or the manual
   research settled an `ambiguous`/`no_source` row. No `merged.json` row has `needs_user` (a wave-1 row
   the user marked `correct` on the wave-1 page counts as settled, since that page applied it). Nothing
   marks the entry for removal, no resolution drops it, and no wave-1 answer is `wrong` or `unsure`
   without a later resolution.
2. Identity. A researcher identity quote is found in its saved body. For entries researched only by a
   resolution, user or manual row, their title quote stands in (4 approvals).
3. Every field. Each field of the current entry except `ID` and `ENTRYTYPE` must be covered. The latest
   research decision on the field (order: resolution batches, newest first; cross-wave answers; manual
   research; each wave, newest first, as post-check value, then reviewer value, then researcher row; the
   pilot) must equal the entry's value after the house normalisation. That is the post-check's own
   normalisers for names, pages, issue ranges, ordinals, proceedings booktitles, em dashes and US
   addresses, then LaTeX letters to Unicode, braces dropped, dashes, spacing and case folded. A
   withdrawn change leaves the cited value, and a removal must have removed the field. The value must
   then be quoted: a quote found in its saved body, and the value's words inside the found quotes
   (`value_supported`; all quotes for resolution values). The user's inference rules count: end page
   from the next item's start (7 fields), catalogue extent `N p.` (2), volume from a roman page prefix
   (1). `url` and `howpublished` need an equal value whose quote is found, without the word test, as in
   validate.py.
4. Entry type. The latest evidence that names an entry type names this one.
5. Context. No DOI-linked notice, PubMed suffix conflict, coordinate conflict or Crossref
   `update-to`/`updated-by` is known for the entry's DOI (`preprint_review.context_issues`, as for the
   OSF, bioRxiv and arXiv routes). `Cache.retain_notices` then treats a research approval like any other
   machine approval: a notice learned later reopens it, and only `human_verified` is exempt.

**Fields not required.** None. `NOT_REQUIRED` is empty on purpose: every field in an approved entry has a
quote, including address, publisher, edition, series, chapter, organization, note, url and howpublished.
An entry with any field the research never quoted stays `needs_review`.

**Reviewer and user prose** (a reviewer's `problems` text, a cross-wave answer without a URL and verbatim
quote) is not evidence. Such a value is approved only when another row quotes the same value.

**Browser reads and scans** (user rule, resolution-plan README, round 2). A resolution or manual quote
with no saved body, or one not found in it, counts only when that row's notes say the evidence was read
in a real browser or transcribed from a scan (`says_browser_or_scan`), and only when the quote text
itself contains the value's words. Each such field is flagged `browser_or_scan` in the saved evidence.
The rule was checked against every resolution and manual note. The first version matched any mention of
"browser" or "scan", which approved Mann06 on the note "searches returned no match in the scripted/browser
views". The tightened rule excludes it, "no scan found", "scans lending-only" and fetches "with a browser
UA". Mann06 was withdrawn by the second run. 15 approvals carry the flag (21 fields in total, listed in
`summary.json`): BjorRich89, DamiEtal99a, Elli70, Este59, Frie12, HartWong79, JaspAndr38, KeppEtal68,
Merk14, NichHolm04, Open22, RussJenk54, ShapOlto94, Unde72a, Wick72.

## Offline re-validation

`valid_research_approval` is registered with `verification.register_approval_validator` and imported in
`verification_cli.py`, `.bibcheck/validate-current-checkpoint.py` and this folder's `export.py`. It
checks, in every environment:

- the saved record: every field covered with its exact value and a found quote with a body sha256 (or
  the browser/scan flag), the identity established, no open issue, and `accepted_record_id` equal to
  the hash of that evidence;
- that no DOI-linked evidence among the result's candidates contradicts it.

Where the clone allows, it also re-assesses the saved bundle and requires the identical approval:

- with `.bibcheck/research-pilot/` present, every quote is searched again in its saved body, and a
  missing or changed body (sha256) fails;
- without it (a fresh clone, CI), the recorded quote results are used;
- where validate.py and the post-check cannot be imported (`requirements-research.txt` has no pandas),
  the self-consistency check stands alone. That is the trust `import_snapshot` already gives a saved
  Crossref candidate.

Checked on the real baseline: a fresh import gives the same 6,390 statuses with the body cache, with the
body directory pointed elsewhere, and with the post-check import failing.

## Counts (cdl.bib at 716a122, 1,263 needs_review before)

| Run | Approved | Held by DOI-linked evidence | Not approved | Other | Review writes |
|-|-|-|-|-|-|
| dry run | 928 | 88 | 247 | | 0 |
| backfill | 928 | 88 | 247 | | 1,016 |
| second run (stricter browser rule) | | | 247 | 1 withdrawn (Mann06), 3 re-approved, 88 unchanged | 4 |
| repeat | | | 248 | 88 unchanged | 0 |

The re-approved three (CaoWors99, DaviHink97, Witt02) were rewritten only because their bundles' lenient
marks changed; their quotes are found in saved bodies. Per-entry outcomes are in `dry-run.json`,
`backfill.json`, `backfill-2.json` and `repeat.json`, and the grouping in `summary.json`.

`bibcheck.py crossref status cdl.bib`:

- before: 6390 entries: human_verified=31, metadata_verified=5096, needs_review=1263
- after: 6390 entries: human_verified=31, metadata_verified=6023, needs_review=336

The 927 approvals are 923 with a researcher identity quote and 4 with a resolution title as identity.

### Why the 248 are not approved (first blocking reason)

| Reason | Entries |
|-|-|
| a field of the entry no research row covers (journal 73, author 27, pages 21, address 15, others) | 159 |
| the entry's value is not the latest researched value (a held or `check_bib`-refused change, a later correction not applied) | 31 |
| the value rests on reviewer or user prose, no verbatim quote | 19 |
| value words missing from the quotes | 16 |
| quote not found in its saved body | 6, plus Mann06 |
| verdict ambiguous/no_source, no resolution | 6 |
| post-check `needs_user` residue (ChanEtal12, DougPeuc73, LegaEtal11, McCaEtal06) | 4 |
| a field the research removed is still present (Force on FoodAdmi20a/b; author on GorfHoff87 and LemoPiet12, batch 27) | 4 |
| no saved body for the quoted URL | 1 |
| wave-1 answer `unsure` (Kolo13) | 1 |

All reasons per entry, not only the first, are under `all_reasons` in `summary.json`. The largest group is
entries whose researcher confirmed every field but the journal (ChiEtal01, for one): the row never quotes
a journal, so the route does not approve it.

### DOI-linked notices

The 82 entries held before by "DOI-linked source correction/retraction notice requires adjudication":

- 70 have research evidence for every field. They stay `needs_review`, now with the research candidate
  attached and the issue "Research evidence verifies every field; the approval is held by known
  DOI-linked evidence". The resolution-plan rules auto-verify a content-only erratum only once its text
  is read, and no erratum text is in the evidence. These are ready for the batch review page the rule
  names.
- 12 are not research-approvable anyway: 10 lack a journal quote, VirtEtal20's author list differs, and
  ChanEtal12 has `needs_user`.
- Notice kinds on the cited DOIs (from the stored candidates): Europe PMC "Erratum in" 78, JATS
  correction-forward 39, Crossref correction 31, Crossref erratum 14, "Comment in" 13, and a few
  commentary, preprint, new-version and addendum links.
- No cited DOI has a retraction. The one retraction in these candidate lists (KeleFent10) belongs to a
  different candidate DOI, the Savine & Braver article already noted in `plan-notices.md`. KeleFent10 is
  held by the erratum on its own DOI.

18 more entries are held the same way although their earlier issue named no notice:

- 11 have a Crossref `updated-by` correction on the cited DOI ("DOI registry notice requires
  adjudication"): Brun04, Eich85, GonsPall00, McKiNoso96, Pike84, Pyly73, RubiEtal17, ThomEtal18,
  TokeSomm19, YoneJaco96a, YoneJaco97.
- Fred04 and HeniEtal19 have coordinate conflicts.
- Este91, FrieEtal99, GellEtal14, McDoEtal10 and Murd56 have no DOI, so `retain_notices` checks every
  candidate DOI of their history and finds a notice. That is its rule for every machine approval without
  an accepted DOI.

## Files

- `export.py`: exports `verification/baseline.jsonl.gz` and `review-queue.jsonl.gz` as the apply runners do.
- `summarize.py`: writes `summary.json` (grouped reasons, flags, notice entries).
- `dry-run-2.json`: per-entry outcomes of the updated route (dry run, no review rows written).
- `.bibcheck/research-route-2026-09-27/`: cache backup before the backfill (`verification-before.sqlite3`),
  run logs, and the previous checkpoint validator. The fresh restore
  (`.bibcheck/validate-current-checkpoint.py`, now importing `research_route`) gave 6,390 restored,
  0 repeat imports, sqlite ok (`../completion-2026-09-15/restore-latest.json`).

## Update 2026-09-27: rules settled since the route was built

The rules are the "(default)" and "(plan)" lines of `../resolution-plan-2026-09-22/README.md` and the notice
classification in `../resolution-2026-09-27/NOTICES.md`. Tests use real rows frozen by
`tests/fixtures/research_route/build.py v2` into `tests/fixtures/research_route/v2/`.

1. **Evidence.** Resolution batches 28-39 are read. All 12 files were valid JSON at the run and committed in
   6a6f7e3. The route reads a resolution set with the post-check's own `evidence_items`, so the union of
   `evidence`/`extra_evidence` quotes covers the value. It applies the post-check's `inferred_end_page`
   (`next_start`), `catalogue_extent` ('N p.' gives 1--N) and `roman_page_prefix` (volume), in
   `resolution_quote`'s order: with a `next_start`, only the end-page rule applies. As in
   `resolution_quote`, a set with an item missing its URL or quote is refused. `apply` in one batch and
   `keep` in another no longer conflict, because both settle the entry. A `drop` beside either still does.
   When no claim is supported, the reason given is the latest claim's.
2. **Start-only chapter pages.** Some chapters (`@incollection`/`@inbook`) have a range `S--E` that a
   resolution or manual row keeps under the partial-confirmation default. Its notes say "confirms the start
   page", "the start page 64 is confirmed", "partly-confirmed" and so on (`PARTIAL_PAGES`). Such a range is
   approved with the flag `pages_start_only` when a found quote prints `S`. The quote is the pages claim's
   own. When no row quotes the pages, it is a quote from the same row that the notes name ("R A RESCORLA
   A R WAGNER 64"). A quote that prints `S` with another end page refuses it. A browser-read quote also
   carries `browser_or_scan`. Approved this way: RescWagn72, Slam87, Frie79.
3. **Identity.** When the researcher's identity quote has no saved body, a resolution, cross-wave or manual
   title quote that verifies serves as the identity (`from_field: title`). The route already allowed this
   before the update, and it still does when the researcher's quote is missing from a saved body. Keeping
   that looser behaviour avoids withdrawing CaoWors99, KnigEtal04 and Schw78. It also approves Bull90 and
   BunnEtal99. A stricter version was measured, and it would have withdrawn those three and held the
   other two.
4. **Notices.** Each research bundle carries its classified notices. `notice_adjudication` settles
   them as follows:
   - `content_only`: approved.
   - `metadata_correction`: approved when every corrected value is already in the entry. The corrected
     name must be one of the entry's names.
   - `unread`: approved with `notice_unread` when the notes record that there is no retraction.
   - `new_version`: approved when "no citation field changes".
   - `cited_work_is_notice`, `unrelated`, `no_notice`: ignored.
   - `coordinate_conflict`: the entry must carry the Crossref value.
   - `retraction` and `expression_of_concern`, or any unknown class: never approved.

   Two further conditions:
   - Every notice is flagged `notice: notice_<class>`.
   - A retraction, expression of concern or withdrawal on a saved record of the cited DOI holds the
     approval whatever the classification says (`retraction_signals`). This covers Europe PMC, a
     Crossref update and a JATS related-article. KeleFent10's retraction is on another work's record and
     is ignored.

   `merge` and `valid_research_approval` accept a DOI-linked hold that the classification settles. The
   adjudication is part of the evidence id. Unclassified notices still hold.
5. **Group names.** `canon` reads an author or editor name that the entry prints as one braced group
   (`{RNS System in Epilepsy Study Group}`, or double-braced) as that group, braced or not, instead of
   initialling it.

### Cache.retain_notices: the notice-accounting hook (resolved 2026-09-27)

`Cache.retain_notices` (`bibcheck/verification.py`) reopens a machine approval when the cache knows a
DOI-linked notice, PubMed-suffix or article-locator record for its DOI. A route can now declare that its
approval already accounts for specific notices, and `retain_notices` keeps it only when all of this holds:

- The route registered a hook for its `accepted_source` (`register_notice_accounting`). Only the research
  route has one (`research-evidence` → `research_route.accounts_for_notices`). `verification.py` imports
  that module on demand, so a script that never imported the route does not reopen and rewrite the row.
- The result carries `notices_accounted`: the route, the cited DOI, the DOIs of the notices the
  classification settled (`notice_dois`), and the identity of each DOI-linked record of the cited DOI
  the classification was applied beside (`records`, the identity the notice tables store).
- Every record the cache knows for the entry is in `records`. A record learned later has a new identity,
  for example a Europe PMC record that now lists a second "Erratum in", so it reopens the entry.
- The hook accepts the result with every known record attached. It requires that the approval was made
  for the entry's current fields and that the declaration is the one the approval's own saved
  classification and records give (`notices_declaration`). `valid_research_approval` must then hold,
  which covers the classification and `retraction_signals`.

`notices_declaration` declares nothing in these cases: the entry has no DOI, no notice is classified, a
classified notice is unsettled, or a record carries more notice links than the classification settled.
Notice links are Europe PMC "Erratum in"/"Retraction in"/... and JATS `correction-forward`/
`retraction-forward`/..., not comments, preprints or companions. The slots are the rows classed
`content_only`, `metadata_correction` or `unread`. The saved links carry no notice DOI, so a notice is
matched to its record by this count and by the record identity, not by DOI. Entries without a DOI (Este91,
FrieEtal99, GellEtal14, McDoEtal10, Murd56), and entries whose only record the classification does not
cover, were still reopened (until the record-identity extension below).

Tests (`tests/test_research_route.py`): the kept approval (AfraEtal06, a Cache.put, a later get and the
backfill), and five negative controls. A notice learned later reopens the entry, before and after it is
stored. A missing, emptied or self-extended declaration reopens it, and so does an approval made for other
field values. A retraction record reopens it even when declared. Other `accepted_source` values carrying
the same declaration are still reopened.

### Notices with no DOI: record identity (2026-09-27, mop-up)

A classification row can now name the exact DOI-linked records it was made beside, in `records`:
`[{"doi": <DOI the record is filed under>, "identity": <notice_record_identity(record)>}]`. The identity is
the digest the cache's notice, PubMed-suffix and article-locator tables store for the record, so any change
to the record (a new "Erratum in" link, another author) gives a new identity. URLs are never used. This is
for notices with no registered DOI (old errata that PubMed lists only as "Erratum in") and for records that
are no notice at all: PubMed author-suffix records (`no_notice`), PMC article-locator records
(`coordinate_conflict`), and another candidate's record (`unrelated`). The declaration then carries
`notice_records` (only when a row names one), and `notices_accounted_for` accepts `notice_dois` or
`notice_records`. Declarations by notice DOI alone are unchanged, so stored approvals re-derive the same
declaration.

`notices_declaration` refuses (declares nothing) when a row identifies nothing (no notice DOI and no
`records`), a name is malformed (not a 64-hex identity, no DOI), a record named by a no-notice class carries
a notice link, an `unrelated` name is filed under the cited DOI, a `no_notice`/`coordinate_conflict` name is
filed under another DOI, or none of the names is a record the approval stands beside. Without a notice DOI,
every DOI-linked record must be named, except matching article-locator records, which `retain_notices`
passes over. An entry without a DOI is checked against every candidate DOI (as `retain_notices` does), so
Este91-like entries must name each record. The link-count rule still applies to every record, and
`valid_research_approval` still rejects any retraction signal.

Tests: McDoEtal10 (suffix record) and Fred04 (locator record) named by identity are kept, and are reopened
without the names. AfraEtal06's erratum stripped of its DOI and named by its Europe PMC record is kept, and
a later erratum link reopens it. A different suffix record of the same DOI with no classification reopens
the approval, whether learned before or after the put, and a hand-made declaration listing it is refused by
the hook. Names that do not fit the class, malformed names and names of absent records declare nothing. A
named retraction record is still refused. Este91 (no DOI) is kept only with the unrelated candidate's record
named, and another unnamed record reopens it. Existing DOI declarations keep their four keys.

### Mop-up rules (2026-09-27, later)

**Renames for batches keyed as committed.** Resolution batches from 27 on were written against the cdl.bib of
their commit (apply-2026-09-30-final README: "Every key was found in cdl.bib as written"). Their rows now follow
only the renames logged after the batch was committed (`renames_when_committed`: the length of
`key-renames.json` in the commit that added the batch, by git; the old log must be a prefix of the current one,
or the route raises). Before this, batch 30's `Frie08` row (Friendly's *Handbook of Data Visualization* chapter,
keyed Frie08 since the wave-8 renames) followed Frie08 -> Frie08a -> Frie12 and landed on Friedman's chapter:
Frie12 was held because its editors were not Chen, Härdle and Unwin, and Frie08 because nothing quoted them.
FINAL.md's "apply batch 30's editor value to Frie12" would have given Friedman's chapter Friendly's editors; it
was not applied. Batches 1-26 name entries by older keys (batch 23's `Frie08` is the Frie08 that became Frie12)
and still follow the whole log. A layout that is not the top of a git work tree (the frozen test fixtures)
follows the whole log, as before.

**Post-check residue a resolution settles.** A merged `needs_user` row that the user did not mark correct now
keeps the post-check's reasons (`residue`, from `postcheck.needs_user`: the resolution residue, the unresolved
verdict, held/open flags, a key plan other than keep). Rows the user marked correct are unchanged, so stored
approvals re-derive the same bundle. With a later resolution decision `apply`/`keep` (and no `drop`), the row
no longer holds the entry when every reason is one of: an unresolved verdict; `field_not_found` (the every-field
rule quotes each field the entry has); `not_in_bib`/`duplicate` flags or a `duplicate` key plan when the row's key
was merged into this entry (ChanEtal12b, LegaEtal11a); the DOI residue of an unavailable Crossref record when
the entry carries the DOI (the McCaEtal06 DOI default). Any other reason still goes to the user.

**Mop-up batch.** `batch-40.json` in this folder holds resolution rows in the batch schema (ElliAshb88, Mann06),
read as resolution batch 40 (newest, keyed as committed) and listed by `uncommitted_evidence`.

### Dry run (`dry-run-2.json`; cdl.bib and evidence at 6a6f7e3, a copy of the verification cache)

`bibcheck.py crossref status cdl.bib` before: 6390 entries: human_verified=31, metadata_verified=6023,
needs_review=336.

| Outcome for the 336 needs_review | Entries |
|-|-|
| approved (research evidence for every field; notice settled or none) | 173 |
| route approves, `Cache.retain_notices` reopens (see above) | 78 |
| held: notice not classified (BarrEtal18, JohnEtal98, MankEtal12, MarkEtal95a, MonaAbbo11, RebeEtal02, RutiEtal08, SohnEtal00, StarDava06, VirtEtal20, WangBuzs96, WheeEtal00) | 12 |
| held: coordinate conflict, Crossref's article number not yet in the entry (HeniEtal19) | 1 |
| not approved | 72 |

The 72 not approved:

| Reason | Entries |
|-|-|
| the entry does not yet carry the latest researched value or removal (pending cdl.bib edits; includes Ande76 and Huth13, whose identity is their pending title) | 61 |
| post-check `needs_user` (ChanEtal12, DougPeuc73, LegaEtal11, McCaEtal06; Kolo13 also has pending removals) | 5 |
| a resolution drops it (ElliAshb88: batch 18 keeps and batch 30 drops, see the plan's note; EngeEtal93; Rayp68) | 3 |
| editor words not in the quotes and volume unresearched (Frie08) | 1 |
| `type` quote not in its saved body (Mann06) | 1 |
| author never researched (SvenEtal24, the open 'Hoang NT' question) | 1 |

One current research approval would be withdrawn: Frie12. Batch 30 sets an editor value that cdl.bib does
not carry yet.
