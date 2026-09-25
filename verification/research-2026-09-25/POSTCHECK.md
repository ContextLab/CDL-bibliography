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
| DOI record title | `doi_title_mismatch`, `doi_title_unavailable` | The Crossref/DataCite title (plus subtitle, minus a leading "Chapter N") must match the entry's title, chapter or booktitle after folding case, accents, braces and punctuation (equal, title+subtitle, or 85% word overlap); else the DOI change is dropped |
| DOI record fields | `doi_record_conflict`, `print_year_conflict` | Record pages or issued year that differ from the proposal are flagged; a `published-print` year that differs is a print-year conflict (print year wins, suggested) |
| Print year | `print_year_conflict`, `year_from_online_date` | A print date in the notes (a clause with "print"/"printed", not "reprint") that differs from the year is flagged with the print year suggested; year evidence that is only an online date is flagged |
| Patents | `patent_filing_year`, `patent_year_unproven`, `patent_number_missing` | For a patent (@patent, patent URL or notes), year evidence mentioning filing/priority/application/submitted holds the year; the grant year from the notes is suggested |
| Keys | `key_rename`, `duplicate`, `key_collision` | The house ID rule (`helpers.authors2key` on author, or editor when there is no author, and year) is computed for the final entry. If the current key does not fit it (suffix letters allowed, `key_overrides.json` honoured), it is a rename. If the new base key exists in cdl.bib: same work (title, first-author surname and year) = "duplicate, merge into <key>"; a different work = collision, with the next free suffix per house practice (an unsuffixed holder becomes `a`, the new entry the next letter, as with LeeEtal20 -> LeeEtal20a/LeeEtal20b). A shared DOI with another entry is also reported as a duplicate. Keys renamed away in `verification/key-renames.json` are reported if reused |
| Names (author, editor) | normalisation | No suffixes (Jr, Sr, II, III, IV, also inside braces: `H {Daum\'{e} III}` -> `H {Daum\'{e}}`); full given names to initials (`Jean-Pierre` -> `J-P`); initials without periods; then `helpers.reformat_author`. Braced corporate names and particles are kept |
| Initials from evidence | `initials_from_source` | Given names the author evidence prints (Crossref given/family, PubMed LastName/ForeName, MEDLINE FAU, or "Given Surname" text) extend the initials (`S Hawking` -> `S W Hawking`) or hyphenate them (`J P Michel` -> `J-P Michel`) when every source form agrees; an initial is never removed |
| Surname respelling | `surname_single_source` | A new surname that respells a cited one (similarity >= 0.75) with quotes from fewer than two source hosts is flagged for corroboration or sign-off (README rule) |
| US addresses | normalisation, `us_address_state_unknown` | `City, United States`/`USA`, `City, NJ`, `City, N.J.`, `City, Texas` -> `City, {ST}`; the city's state comes from cdl.bib's own `City, {ST}` addresses, then a small table of unambiguous cities; other addresses go through the house address formatter |
| Ordinals | normalisation | Numeric ordinals in text fields -> `N\textsuperscript{st/nd/rd/th}` with the correct suffix (URLs untouched); editions `Second`/`2nd ed.` -> `2\textsuperscript{nd}` |
| Issue ranges, pages | normalisation | `3-4` -> `3--4`; page ranges `start--end`, abbreviated end pages expanded (`347-76` -> `347--376`) |
| Proceedings booktitle | normalisation | Years removed from proceedings/conference/meeting/NeurIPS booktitles |
| Entry types | normalisation, `invalid_entrytype` | `@conference` -> `@inproceedings`; a titled chapter (`@inbook` with a chapter title, or with a booktitle) -> `@incollection` with title = chapter, booktitle = book; an ENTRYTYPE that is not a BibTeX type (a sentence) is dropped |
| @book, @article | normalisation | `@book` has no pages; `@article` has no publisher (listed under removals) |
| House formatters | normalisation, `booktitle_case` | Title, journal and publisher go through `helpers.format_title`/`format_journal_name`; output that alters brace-protected text or lowercases an inner capital (O'Reilly) is rejected |
| Spacing-only change | `style_only_change` | A title/booktitle/journal change that differs only in whitespace (EngeFrie10 `--- signalling`) is a house-style question, flagged |
| Verdicts | `verdict_inconsistent`, `verdict_understated`, `needs_user` | `verified` with a corrected field; `correction` with none; `ambiguous`/`no_source` although identity is quoted and every field confirmed |
| Reviewer merge | `reviewer_dropped`, `reviewer_disagrees`, `reviewer_action` | Each `suggested_value` replaces the researcher's value (source `reviewer`); a null/empty suggestion withdraws the researcher's change (never an empty value); a field the reviewer disagrees with and gives no value for is held; the reviewer's `key` is compared with the computed key plan (`reviewer_agrees`) |

The rules run twice: once without the review (measurement) and once with it (final
output). House normalisations run after the merge, so reviewer values are normalised too.

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

Rerun: `.venv/bin/python verification/research-2026-09-25/postcheck.py verification/research-2026-09-25/wave1`
(the second run makes no network requests).
