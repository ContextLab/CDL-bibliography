# Research post-check (2026-09-25)

`postcheck.py <wave folder>` is a deterministic check that runs after the research
agents. It reads the wave's `batch-*.json` (schema:
`../research-pilot-2026-09-24/PROTOCOL.md`), the wave's `validation.json` (quote
checks) and `review.json` (independent review) when they exist, and the **committed**
`cdl.bib` (`git show HEAD:cdl.bib`, or `--bib PATH`). It writes two files into the wave
folder and never edits `cdl.bib`:

- `postcheck.json`: per key the flags, normalisations, final changes, held fields,
  unverified suggestions, key plan and DOI status; a summary (flag counts, dropped DOIs,
  renames, duplicates, collisions); and the review measurement.
- `merged.json`: one row per entry for the user's review page: key, current fields,
  final changes (each with `source` = researcher / reviewer / postcheck, its evidence,
  and the reviewer's field verdict), removals, key plan, flags, DOI status, reviewer
  agreement, and `needs_user`.

Network responses (doi.org handles and RA, Crossref, DataCite) are cached under
`.bibcheck/research-postcheck/` and paced at 0.4 s; `--offline` uses the cache only, and
a DOI that cannot be checked is held, never passed. Tests:
`tests/test_research_postcheck.py` (real wave-1 rows, committed bib, live cached
registry records, a negative control for each rule; no mocks).

## Rules

Each rule records a flag `{code, field, detail, action}`; `action` is `applied`,
`dropped` (the change is removed), `held` (not applied, needs the user) or `flag`.

| Rule | Code(s) | What happens |
|-|-|-|
| Only `confirmed`/`corrected` fields apply; `not_found` values and all fields of a `no_source` entry never change the entry | `field_not_found`, `unverified_suggestions` | A differing not_found value is listed as a suggestion; a `verified`/`correction` verdict with any not_found field is flagged as not fully verified |
| Never apply an empty value | `empty_value` | Held; a removal the researcher intended (e.g. Frie06 `volume`) is the user's decision |
| Quote check | `quote_check_failed`, `identity_quote_failed` | A field whose quotes failed `validate.py` is held |
| DOI registration | `doi_unregistered`, `doi_check_failed` | Every proposed DOI must return responseCode 1 at `https://doi.org/api/handles/<doi>`; otherwise the DOI change is dropped (404) or held (check failed) |
| DOI record title | `doi_title_mismatch`, `doi_title_unavailable` | The Crossref/DataCite title (plus subtitle, minus a leading "Chapter N") must match the entry's title, chapter or booktitle after folding case, accents, braces and punctuation (equal, title+subtitle, or 85% word overlap) with the same part numbers (`... cortex II` is another work); a registry title that is the entry's title plus an appended footnote (a number glued to the last word, `*`, a dagger: WoodEtal00b's Crossref title ends `inpatients11The percentage of nights...`) also matches. Otherwise the DOI change is dropped (BoddEtal97's generic `Correspondence` still is) |
| DOI record fields | `doi_record_conflict`, `print_year_conflict` | Record pages or issued year that differ from the proposal are flagged; a `published-print` year that differs is a print-year conflict (print year wins, suggested), unless the year's own evidence quotes the proposed year as a print date from two or more source hosts (Europe PMC `printPublicationDate`, PubMed `<PubDate><Year>`, MEDLINE `DP`, `published-print`): then the Crossref deposit is only a `doi_record_conflict` and no year is suggested (Bastvand05: PubMed and Europe PMC print 2006, Crossref deposits 2005) |
| Print year | `print_year_conflict`, `year_from_online_date` | A print date in the notes (a clause with "print"/"printed", not "reprint") that differs from the year is flagged with the print year suggested, unless the year's print date is corroborated as above; year evidence that is only an online date is flagged |
| Patents | `patent_filing_year`, `patent_year_unproven`, `patent_number_missing` | For a patent (@patent, patent URL or notes), year evidence mentioning filing/priority/application/submitted holds the year; the grant year from the notes is suggested |
| Duplicates | `duplicate` | The final entry is compared with every cdl.bib entry, with or without a DOI: same title (same part numbers), first-author surname and year = the same work (CronEtal98a gains a DOI; CronEtal98c in HEAD, no DOI, is the same Part II paper). The later key merges into the earlier; the earlier gets a flag. Within one wave, two rows that end with the same DOI or the same work are flagged the same way |
| Keys | `key_rename`, `duplicate`, `key_collision` | The house ID rule (`helpers.authors2key` on author, or editor when there is no author, and year) is computed for the final entry. If the current key does not fit it (suffix letters allowed, `key_overrides.json` honoured), it is a rename. If the new base key exists in cdl.bib: same work (title, first-author surname and year) = "duplicate, merge into <key>"; a different work = collision, with the next free suffix per house practice (an unsuffixed holder becomes `a`, the new entry the next letter, as with LeeEtal20 -> LeeEtal20a/LeeEtal20b). A shared DOI with another entry is also reported as a duplicate. Keys renamed away in `verification/key-renames.json` are reported if reused |
| Names (author, editor) | normalisation | FORMAT only: no suffixes (Jr, Sr, II, III, IV, also inside braces: `H {Daum\'{e} III}` -> `H {Daum\'{e}}`, `Engel, J Jr` -> `J Engel`); full given names to initials (`Jean-Pierre` -> `J-P`); initials without periods; then `helpers.reformat_author`. Names printed in capitals are put in ordinary case first, so a given name is never spelled as single letters (`EUGENIO RODRIGUEZ` -> `E Rodriguez`, not `E U G E N I O`): a capitalised token of four or more letters is a word, and in a name printed wholly in capitals a two- or three-letter token with a vowel is too; `JP Smith` stays `J P Smith`. Braced corporate names and particles are kept. Author values change only as the researcher (or reviewer) proposed them: the post-check never reads initials from the sources and never adds or removes an initial (the former `initials_from_source` rule is removed, see the wave-3 fixes) |
| Surname respelling | `surname_single_source` | A new surname that respells a cited one (similarity >= 0.75; not a brace or spacing fix of the same letters such as `{Schurman n}` -> `Sch{\"u}rmann`) with quotes from fewer than two source hosts is held: that author keeps the whole cited name (house format) and the flag names the proposed surname for corroboration or sign-off (README rule; FreeEtal03b keeps `R Jornten`, not Crossref's deposit typo `Jorsten`). The hold is released (`applied`, source `reviewer`) when the reviewer's author verdict confirms it (`agree ...`), and a reviewer's own author value replaces it |
| US addresses | normalisation, `us_address_state_unknown` | `City, United States`/`USA`, `City, NJ`, `City, N.J.`, `City, Texas` -> `City, {ST}`; the city's state comes from cdl.bib's own `City, {ST}` addresses, then a small table of unambiguous cities; other addresses go through the house address formatter |
| Ordinals | normalisation | Numeric ordinals in text fields -> `N\textsuperscript{st/nd/rd/th}` with the correct suffix (URLs untouched); editions `Second`/`2nd ed.` -> `2\textsuperscript{nd}` |
| Issue ranges, pages | normalisation | `3-4` -> `3--4`; page ranges `start--end`, abbreviated end pages expanded (`347-76` -> `347--376`) |
| Proceedings booktitle | normalisation | Years removed from proceedings/conference/meeting/NeurIPS booktitles |
| Field names | normalisation | Field names are case-folded (`entrytype`, `EntryType` -> `ENTRYTYPE`; `Journal` -> `journal`) in researcher rows, reviewer values and verdicts, and validation rows, so a lowercase `entrytype` is the type change (AllpEtal94) |
| Entry types | normalisation, `invalid_entrytype` | `@conference` -> `@inproceedings`; a titled chapter (`@inbook` with a chapter title, or with a booktitle) -> `@incollection` with title = chapter, booktitle = book; an ENTRYTYPE that is not a BibTeX type (a sentence) is dropped |
| @book, @article | normalisation | `@book` has no pages; `@article` has no publisher (listed under removals) |
| Article number | normalisation | When pages changes to a single article number and `number` holds the same value, `number` is removed (Brig12, JayaEtal23, CookEtal16, AfshEtal13, NastEtal18). A different issue number stays (FoxGrei10's 10 against article 19) |
| @misc | normalisation | `@misc` has no journal, and a `volume` holding a URL is removed (Hint12's Class Central link); a plain volume stays |
| Researcher removals | normalisation | A row's top-level `"remove": [field, ...]` is honoured: the fields go (listed under removals), unless the reviewer supplied a value for one |
| No journal on contained types | normalisation | `@inproceedings`/`@incollection`/`@inbook` have no journal (listed under removals): dropped when the booktitle or series already gives it (NeurIPS, SchaTurk15, MayeEtal92b), moved to booktitle when there is none, moved to series when the booktitle differs and there is no series (a book series given as the journal), but dropped when the journal names the same venue as the booktitle (`same_venue`: at least two content words, 80% of them in the booktitle, ignoring function words and generic venue words such as proceedings/annual/conference; DesaEtal12, BoseEtal92). A volume that is the series number already printed in the booktitle (`Attention and Performance {XV}`, volume 15) is removed too |
| House formatters | normalisation, `booktitle_case` | Title, journal and publisher go through `helpers.format_title`/`format_journal_name`; output that alters brace-protected text or lowercases an inner capital (O'Reilly) is rejected |
| Spacing-only change | `style_only_change` | A title/booktitle/journal change that differs only in whitespace (EngeFrie10 `--- signalling`) is a house-style question, flagged |
| Verdicts | `verdict_inconsistent`, `verdict_understated`, `needs_user` | `verified` with a corrected field; `correction` with none; `ambiguous`/`no_source` although identity is quoted and every field confirmed |
| Reviewer merge | `reviewer_dropped`, `reviewer_disagrees`, `reviewer_action` | Each `suggested_value` (every wave's `review.json`: waves 1, 2 and 3) replaces the researcher's value (source `reviewer`) and releases a quote-check hold on that field; a null/empty suggestion withdraws the researcher's change (never an empty value); a field the reviewer disagrees with (`disagree`, `disagree: ...`) and gives no value for is held. A field held only because the validator could not read the source (every failure a fetch failure, or the whole page failed: identity and all fields `quote not found`, as with Project Euclid's block page) is applied with source `reviewer` when the reviewer's verdict confirms it (`agree ...`, `disagree (held but correct)`); a quote that fails on a page that was read (Hint84 volume) is not released this way. The reviewer's `key` is compared with the computed key plan (`reviewer_agrees`) |

The rules run twice: once without the review (measurement) and once with it (final
output). House normalisations run after the merge, so reviewer values are normalised too.

`review_resolution` in `postcheck.json` checks each reviewer finding against the final
output (rules + reviewer merge): every suggested value is the final value; a field the
reviewer says must be removed or should go is absent; a key called a duplicate has a
duplicate plan or flag, and a suggested key equals the key plan; any other disagreement
without a value leaves the field as in cdl.bib. A finding with only `unsure` verdicts is
not checkable. `review_resolution_rules_alone` runs the same checks on the pass without
the review.

## Wave 1 measurement (2026-09-25)

`measurement` in `postcheck.json` counts a reviewer finding (a row with `agree` other
than `yes`) as caught when a rule, run **without** the review, flags or normalises one
of the fields the reviewer disputed or suggested a value for. That proxy gives
**24 of 29** findings and **10 of 10** random-sample findings. The manual audit below
checks whether each hit is the reviewer's actual point.

| Key | Sample | Reviewer's point | Post-check (rules alone) | Audit |
|-|-|-|-|-|
| GoenEtal08 | a | duplicate of GoenLogo08 | duplicate, merge into GoenLogo08 | caught |
| DawKenj06 | a | duplicate of DawDoya06 | duplicate, merge into DawDoya06 | caught |
| Frie06 | a | Frie08 collision | collision; Frie08 -> Frie08a, new Frie08b (reviewer said Frie08a) | caught |
| KleiEtal07b | a | unregistered T&F DOI | DOI dropped; @incollection | caught |
| Este91 | a | unregistered DOI; verdict should be correction | DOI dropped; verdict flagged; @incollection | caught |
| Jell02 | a | pages conflict PubMed vs Crossref | Crossref pages 347-384 vs 347--376 flagged | caught (entry-type question not raised) |
| Chri92 | a | subtitle unverified | validator hold on title | caught |
| MannEtal23b | a | Manjunatha rests on one source | single-source surname flag | caught |
| Mann06 | a | ENTRYTYPE is a sentence | invalid ENTRYTYPE dropped | caught |
| Nati24b | a | year unsourced; author change renames key | year not_found flagged; rename Schn24 | caught |
| IyyeEtal15 | a | suffix III kept | III stripped | caught (fixed) |
| BeckBurg01 | a | year and pages unverified | both flagged not_found | caught |
| HeatEtal93 | a | author resolvable from publisher page | author flagged not_found | surfaced only (source not found) |
| VandEtal99 | a | ambiguous is resolvable (LoC) | @incollection with chapter title; pages conflict | partial (resolution not found) |
| ChenEtal22 | b | address should be Seattle, {WA} | Seattle, {WA} | caught (fixed) |
| EchaEtal00 | b | patent dated by filing year | year held, grant 2004 suggested | caught |
| LittEtal98 | b | patent dated by priority year | year held, grant 2003 suggested | caught |
| EngeFrie10 | b | dash spacing is a house-style change | spacing-only change flagged | caught |
| GoebLewa91 | b | unregistered DOI | DOI dropped | caught |
| PetzHaub04 | b | unregistered DOI | DOI dropped | caught |
| WardEtal09 | b | unregistered DOI; should be @incollection | DOI dropped; @incollection | caught (fixed) |
| GoldEtal05 | b | J P should be J-P | J-P from PubMed ForeName | caught (fixed) |
| Hawk99 | b | S W Hawking; '?' not in source | S W Hawking | partial: author fixed, title '?' not caught |
| KansEtal15 | b | print year 2017 vs 2015 | print-year conflict, 2017 suggested | caught |
| Wech45 | a | resolvable to the 1945 article | verdict_understated only | missed |
| Wech81 | a | Harvard/Open Library record exists | nothing | missed |
| TurlWhit03 | a | ambiguous overstates; author hold | nothing | missed |
| EngeEtal93 | a | notes' suggested form keeps Jr | nothing (the form is in notes, no fields) | missed |
| LincNati81 | a | corporate added entry is not an author | nothing | missed |

Audit totals: **22 of 29 caught** with the reviewer's diagnosis (five of them fixed
automatically: IyyeEtal15, ChenEtal22, WardEtal09, GoldEtal05, and Hawk99's author),
2 surfaced or partial (HeatEtal93, VandEtal99), 5 missed. Random sample: **9 of 10
caught fully, Hawk99 partly** (its author fixed, the unsupported '?' not caught).

What the rules cannot catch: a missed source (a catalogue or publisher page the
researcher did not find: HeatEtal93, Wech45, Wech81, VandEtal99), a judgment about
work form or verdict (TurlWhit03, LincNati81's corporate added entry, Jell02's entry
type, Mann06's thesis type), proposals written only in `notes` (EngeEtal93), and
punctuation that the quote checker ignores (Hawk99's '?').

Outside the review set: the three other unregistered T&F chapter DOIs (JacoEtal97,
Mand91, NilsGard91) are dropped, and HerrEtal09 -> HerrEtal10 is a collision
(HerrEtal10 -> HerrEtal10a, new HerrEtal10b).

Other rule output on wave 1 that needs a look: the title check dropped two DOIs whose
registry title differs, BoddEtal97 (Crossref deposits the title as "Correspondence"
with no authors, a deposit error; the DOI is probably right) and BaayEtal95 (DataCite
"CELEX2" vs "The {CELEX} lexical database"); WernSchm99's DOI is held because its
Crossref record has no title. Print-year conflicts from Crossref: Post69 (print 1970)
and Bord08 (print 2012).

## Wave 2 review fixes (2026-09-25)

The wave-2 reviewer (25 findings of 93) found that the post-check itself caused most
remaining errors. Fixed, each with a regression test on the real wave-2 rows:

- Initials: 8 of 10 `initials_from_source` applications were wrong (DezfDali20
  `M P {Parto Dezfouli}`, DupoEtal00 `D L {Le Bihan}`, SilbEtal03 and CassEtal02
  `V D {Di Lazzaro}`, HoltEtal12 `P R {Riva Posse}`, TingEtal02 `M-L T {Ting Lee}`,
  CowaEtal04 `S D {Della Sala}`, PaszEtal19 `A A D A K{\"o}pf`). Now 2 of 2 applications
  in wave 2, both the ones the reviewer confirmed (AllpEtal94 `S L Hsieh`, MillEtal03 `X-J Wang`). (Superseded: the rule was removed after the wave-3 review.)
- 17 type conversions kept Journal next to Booktitle: journal removed (MayeEtal92b's
  duplicates its series; AllpEtal94's volume 15 is the `{XV}` in its booktitle, removed).
  The same rule removes Journal from wave 1's BeckBurg01, EngeEtal93 and BranEtal04.
- AllpEtal94's lowercase `entrytype` is now the type change.
- CronEtal98a / CronEtal98c (same Part II paper, the second without a DOI) are a duplicate.
- WoodEtal00b's DOI is kept (Crossref title plus footnote).
- CaoWors99, Schw78, Hint84: the reviewer's values replace the fetch-blocked or
  mis-scoped holds.

Resolution after the fix (`review_resolution`):

| Wave | Findings | Resolved (rules + reviewer merge) | Rules alone | Unresolved | Not checkable |
|-|-|-|-|-|-|
| 1 | 29 | 24 | 13 | Frie06 (reviewer says Frie08a; the house suffix rule gives Frie08 -> Frie08a, new Frie08b) | BeckBurg01, Jell02, Chri92, KansEtal15 (`unsure` verdicts: user decisions) |
| 2 | 25 | 25 | 22 | none (CaoWors99, Schw78, Hint84 need the reviewer's values) | none |

The wave-1 "resolved" count relies on the reviewer's values for the findings the rules
cannot catch (missed sources, work form); it says the final output carries the
reviewer's values, not that the rules found them (see the audit above).

## Wave 3 review fixes (2026-09-25)

The wave-3 reviewer (95 reviewed, 8 findings, random-sample error 1.9%) again found the
post-check behind most remaining errors. Fixed, each with a regression test on the real
wave-3 rows and a negative control:

- Initials: 5 of 6 `initials_from_source` applications were wrong (World Scientific's
  capitalised given names read as initials, `E U G E N I O Rodriguez`, `R E B E C K A`,
  `G U N N A R Carlsson`; PubMed `Engel, J Jr` read as `J J Engel` in BragEtal99; a
  PubMed-only middle initial against the publisher's full given name, MeckEtal99
  `A D Mecklinger` vs `Axel`). The rule is removed entirely; names change only as the
  researcher or reviewer proposed them. Consequences: vandEtal17 keeps the researcher's
  `M A {van der Meer}` (the reviewer had called `M A A` right, without a suggested value),
  AllpEtal94 `S Hsieh`, MillEtal03 `X J Wang`; GoldEtal05 and Hawk99 get `J-P` and `S W` from
  the wave-1 reviewer's values. Capitalised names are now put in ordinary case before the
  house formatter.
- DesaEtal12, BoseEtal92: the journal names the same conference as the booktitle, so it is
  dropped, not moved to series.
- Number next to an article number now in pages is removed (five entries); `@misc` loses
  journal and a URL volume (Hint12); the researchers' `remove` lists (18 rows in wave 3) are
  honoured.
- Bastvand05: the Crossref deposit year 2005 is no longer suggested against PubMed's and
  Europe PMC's print date 2006.
- The single-source surname hold now actually holds: the cited name is kept (it was
  flagged "held" but applied before). FreeEtal03b keeps `R Jornten` without the review and
  gets the reviewer's `R J{\"o}rnsten` with it. Holds the reviewer confirmed (wave 3:
  Brig12, BrigEtal18, BoseEtal92, JohnEtal08, BurkEtal15, RuggEtal96 and others) are applied
  with source `reviewer`. Holds that remain for the user: YeoEtal11, BoddEtal97, BenaEtal87
  (wave 1), NicoEtal00, SerrEtal03, McCuPitt43, AguiEtal96, HowaEtal03 (wave 2), PollEtal00
  (wave 3); most look like typo corrections in cdl.bib and need a second source or sign-off.

Resolution after the wave-3 fixes (`review_resolution`):

| Wave | Findings | Resolved (rules + reviewer merge) | Rules alone | Unresolved | Not checkable |
|-|-|-|-|-|-|
| 1 | 29 | 24 | 13 | Frie06 (house suffix rule, as above) | BeckBurg01, Jell02, Chri92, KansEtal15 |
| 2 | 25 | 25 | 22 | none | none |
| 3 | 8 | 8 | 7 (FreeEtal03b needs the reviewer's surname) | none | none |

Rerun: `.venv/bin/python verification/research-2026-09-25/postcheck.py verification/research-2026-09-25/wave1`
(the second run makes no network requests).
