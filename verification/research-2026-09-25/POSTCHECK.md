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
`.bibcheck/research-postcheck/` and paced at 0.4 s. A rate-limited answer (HTTP 429 or
503) is retried up to 4 times, waiting the server's `Retry-After` (seconds or a date,
at most 120 s) or 5, 10, 20, 40 s without one, and is never cached (wave 4: CeraHend65
and HaymTulv89 were held only on a 429; wave 5: 8 DOIs and 4 quote checks). `--offline`
uses the cache only, and a DOI that cannot be checked is held, never passed. Tests:
`tests/test_research_postcheck.py` (real wave-1 rows, committed bib, live cached
registry records, a negative control for each rule; no mocks).

## Rules

Each rule records a flag `{code, field, detail, action}`; `action` is `applied`,
`dropped` (the change is removed), `held` (not applied, needs the user) or `flag`.

| Rule | Code(s) | What happens |
|-|-|-|
| Only `confirmed`/`corrected` fields apply; `not_found` values and all fields of a `no_source` entry never change the entry | `field_not_found`, `unverified_suggestions` | A differing not_found value is listed as a suggestion; a `verified`/`correction` verdict with any not_found field is flagged as not fully verified. A `no_source` row gets none of the post-check's own house rules either (BairNoma78's chapter move); only a reviewer's value and the junk-field removal apply |
| Ambiguous identity | `ambiguous_identity_held` | On an `ambiguous` verdict the identity-defining changes (title, year, DOI, journal, booktitle; researcher's or reviewer's) are held together as one user decision, never applied piecemeal (Ebbi85 had the 1913 translation's title and DOI with the 1885 year); the titled-chapter move is not made either (`chapter_move_held`) |
| Junk fields | normalisation | `Force` is not a BibTeX field and is always removed (AbdeEtal21, LiEtal24b, Amer23b, ChatGPT) |
| Other version named | `other_version_named` | The batch schema has no structured field for a replacement candidate, so the notes are read: `replacement candidate`, `published version` or `is-preprint-of`, unless `no`/`not`/`never`/`without` precedes it in its clause (`No published version found`), flags the row for the user (TsitEtal19, LiEtal24b, JainHuth18). `journal version` is not a trigger: it is mostly `the journal version is cited` |
| Never apply an empty value | `empty_value` | Held; a removal the researcher intended (e.g. Frie06 `volume`) is the user's decision |
| Quote check | `quote_check_failed`, `identity_quote_failed` | A field whose quotes failed `validate.py` is held |
| DOI registration | `doi_unregistered`, `doi_check_failed` | Every proposed DOI must return responseCode 1 at `https://doi.org/api/handles/<doi>`; otherwise the DOI change is dropped (404) or held (check failed) |
| DOI record title | `doi_title_mismatch`, `doi_title_unavailable`, `doi_title_part_number`, `doi_title_short` | The Crossref/DataCite title (with or without its subtitle, minus a leading "Chapter N") must match the entry's title, chapter or booktitle after folding case, accents, braces, font commands (`\textit{...}`) and punctuation (equal, title+subtitle, or 85% word overlap) with the same part numbers (`... cortex II` is another work: the rule now applies to every comparison, the bare word-overlap test no longer bypasses it). Number words compare as digits (Waug63b: Crossref `2 methods` = `Two methods`); words the registry glued to a capitalised word are split (WehnSrin81: `genusCataglyphis`); a leading section numeral is ignored unless the entry has one (Turi50: `I.—COMPUTING MACHINERY AND INTELLIGENCE`); one registry word may be a one-letter typo of an entry word of five or more letters (ChabEtal98: `padiatric`; two such words do not match). Also accepted: the entry's title plus an appended footnote (a number glued to the last word, `*`, a dagger: WoodEtal00b's `inpatients11The percentage of nights...`); a book review of the entry's title, `Book Review: <title> <reviewed book's authors, publisher, price>` (Mitc09), when the next word is not a part number; and a registry title that is exactly the entry's pre-colon main title (Elsevier/Cell deposit `Hippocampus`, `Gain Modulation`: Eich04, SaliThie00, ShadMovs99, WagnEtal01) when the record's volume or first page equals the entry's (otherwise held, `doi_title_short`). Titles that agree except for part numbers are held (`doi_title_part_number`) unless the record's first page is the entry's (both parts of DamiEtal99a/b are deposited as `The substantia nigra of the human brain`; JacoEtal98 without its `II`: applied with the flag) or the reviewer supplied or confirmed the DOI. A registry title that is the entry's up to a garble or typo (spaces removed, `vs` = `versus`, at most two letters inserted, deleted, substituted or swapped, entry title of 20 letters or more, same part numbers) is accepted (`doi_title_near`, applied) only when the record's first-author surname, year (print or issued), volume and first page all equal the entry's: Curr99 (`intentionalretrieval`, mojibake `oldî¿new`), BousRosn70 (`Free vs unhibited recall`), Mart65 (the entry's own typo `paried`). Otherwise the DOI change is dropped (BoddEtal97's generic `Correspondence` still is); a one-page record `1005-1005` equals pages `1005` Symbols compare as the registries print them (`{\textregistered}` = `®`, `{\texttrademark}` = `™`, `\pm` = `±`: GusmEtal14, LismIdia95), Greek letters as their names (`β` = `$\beta$`), and a registry's HTML/JATS tag is a word break (`D<sub>2</sub>Dopamine` = `D 2 Dopamine`; the near-title part-number test counts digit runs whether glued or not, so `IP 3` = `{IP3}`: HernEtal00, `doi_title_near`). A bare leading chapter number before a capitalised word is ignored like `Chapter N` unless the entry's title starts with a number (Sand80: Elsevier `20 Stage Analysis of Reaction Processes`). A generic column title (Rebe10: Scientific American Mind `Ask the Brains`) is accepted only when the record's volume, issue, first page and year all equal the entry's and its container is the entry's journal (`doi_generic_title`, applied); BoddEtal97's `Correspondence` (Crossref 1996, entry 1997) is still dropped |
| Entry's own DOI | none | A confirmed DOI equal to the entry's current DOI is no change: it is not checked or dropped (Thor13's spurious drop on its `Vol 2` record title) |
| DOI record fields | `doi_record_conflict`, `print_year_conflict` | Record pages or issued year that differ from the proposal are flagged; a `published-print` year that differs is a print-year conflict (print year wins, suggested), unless the year's own evidence quotes the proposed year as a print date from two or more source hosts (Europe PMC `printPublicationDate`, PubMed `<PubDate><Year>`, MEDLINE `DP`, `published-print`): then the Crossref deposit is only a `doi_record_conflict` and no year is suggested (Bastvand05: PubMed and Europe PMC print 2006, Crossref deposits 2005) |
| Print year | `print_year_conflict`, `year_from_online_date` | A print date in the notes (a clause with "print"/"printed", not "reprint") that differs from the year is flagged with the print year suggested, unless the year's print date is corroborated as above. A year whose own part of the clause (split at parentheses, commas, but/while/whereas) calls it an online, digitisation, archive or deposit date and never print is not a print year (AdelEtal95: `its 2008 date is the online digitisation`). A Crossref `published-print` one year before the cited year is only a `doi_record_conflict` (no suggestion) when the year's evidence quotes a January cover date of the cited year (MEDLINE `DP - 1999 Jan`, PubMed PubDate month Jan, Europe PMC `-01`) and the record's volume is the entry's: a January issue printed or deposited late the year before (WiggEtal99: Crossref 1998-10, Neuropsychologia 37(1) January 1999). Year evidence that is only an online date is flagged A year glued to a word by a hyphen is not read (`pre-2000 SfN abstracts`, ReccOKee89). For a conference paper (@inproceedings/@conference, or a proceedings booktitle) whose year evidence quotes the year, a print year in the notes is the proceedings' print (Curran's NeurIPS reprints: VaswEtal17 2017 printed 2018, LiuEtal18): `proceedings_print_year`, no year suggested |
| Patents | `patent_filing_year`, `patent_year_unproven`, `patent_number_missing` | For a patent (@patent, patent URL or notes), year evidence mentioning filing/priority/application/submitted holds the year; the grant year from the notes is suggested |
| Duplicates | `duplicate` | The final entry is compared with every cdl.bib entry, with or without a DOI: same title (same part numbers), first-author surname and year = the same work (CronEtal98a gains a DOI; CronEtal98c in HEAD, no DOI, is the same Part II paper). The later key merges into the earlier; the earlier gets a flag. Within one wave, two rows that end with the same DOI or the same work are flagged the same way Which entry stays is deterministic (`keeper`): the key that fits the ID rule for the work's corrected metadata (RuggAlla00 once K Allan is added to Rugg00), else the earliest key; two entries are never told to merge into each other (a remaining A -> B / B -> A pair is resolved the same way) |
| Keys | `key_rename`, `duplicate`, `key_collision` | The house ID rule (`helpers.authors2key` on author, or editor when there is no author, and year) is computed for the final entry. If the current key does not fit it (suffix letters allowed, `key_overrides.json` honoured), it is a rename. If the new base key exists in cdl.bib: same work (title, first-author surname and year) = "duplicate, merge into <key>"; a different work = collision, with the next free suffix per house practice (an unsuffixed holder becomes `a`, the new entry the next letter, as with LeeEtal20 -> LeeEtal20a/LeeEtal20b). A shared DOI with another entry is also reported as a duplicate. Keys renamed away in `verification/key-renames.json` are reported if reused A key is renamed only when a key-determining field (first-author surname, author count, year) changes: a key that never followed the rule and whose rule key is the same before and after the correction is kept (ChatGPT, not Open23). A reviewer key outside the ID rule (`ChatGPT`) is read as it is |
| Names (author, editor) | normalisation | FORMAT only: no suffixes (Jr, Sr, II, III, IV, also inside braces: `H {Daum\'{e} III}` -> `H {Daum\'{e}}`, `Engel, J Jr` -> `J Engel`); full given names to initials (`Jean-Pierre` -> `J-P`; dotted `J.-A.` and brace-protected `Jean-{A}rcady` -> `J-A`, TrulEtal97); initials without periods; then `helpers.reformat_author`. Names printed in capitals are put in ordinary case first, so a given name is never spelled as single letters (`EUGENIO RODRIGUEZ` -> `E Rodriguez`, not `E U G E N I O`): a capitalised token of four or more letters is a word, and in a name printed wholly in capitals a two- or three-letter token with a vowel is too; `JP Smith` stays `J P Smith`. Braced corporate names and particles are kept. A capitalised particle (De, Di, Del, Della, Den, Der, Du, Da, La, Le, Van, Von, ...) after the initials starts a braced compound surname as cdl.bib writes it (`B A L Di Leone` -> `B A L {Di Leone}`, `F Del Missier` -> `F {Del Missier}`), never an initial (`B A L D Leone` was wrong). A run-together surname follows the form cdl.bib already uses for the same author (same first initial and letters, a spaced form in two or more other entries): MillEtal07d's `M {denNijs}` -> `M {den Nijs}` (five entries). Author values change only as the researcher (or reviewer) proposed them: the post-check never reads initials from the sources and never adds or removes an initial (the former `initials_from_source` rule is removed, see the wave-3 fixes) A full word after the initials of a name without a comma is part of the surname in house form and is never turned into an initial (`A Quattrini Li` stays, it became `A Q Li`: CarvEtal22b, TianEtal20b; SingEtal24's `K Vasuden Alwala`, `K Hou U`, `V Satish Kumar` stay as the researcher left them); it is braced (`A {Quattrini Li}`) only when a source prints that compound as the family name (a `"family"` / `"name"` quote, PubMed LastName, MEDLINE FAU, or the DOI record's families). Full given names (`John Paul Smith`) and the given part of a `Family, Given` form are still initials. Every change the post-check's rules made to a proposed value carries `normalised_by: postcheck` next to `normalised_from` |
| Surname respelling | `surname_single_source` | A new surname that respells a cited one (similarity >= 0.75) with quotes from fewer than two source hosts is held. Not respellings: a brace or spacing fix of the same letters (`{Schurman n}` -> `Sch{\"u}rmann`); a particle fix, compared with the cited name in house form (VogtEtal14: `B A L Di Leone` -> `B A L {Di Leone}`); a mangled suffix (`R J {Robinson I I }` -> `R J Robinson`, KrauEtal13); a leading `and` left by a broken split (`A A {and Artigas}`, ChamEtal03); a restored accented letter (`Par-Blagoev` -> `Par{\'e}-Blagoev`, WagnEtal01); and authors that expand a cited `and others` (YangEtal24). The DOI record the post-check fetched and kept counts as a source host when it lists the surname (wave 5: ToluEtal12 `Changeux`, VanEEtal01 `Dickson`). It is one host: when the researcher's only quotes come from that same Crossref record it adds nothing (Trop86 `Trope`, CrosEtal93 `Crosson` stay held, like FreeEtal03b's Crossref typo `Jorsten` and RuggEtal96's `Patching`). cdl.bib is the other witness it accepts: a respelling with one source host is applied when another cdl.bib entry already writes that surname for the same person (compatible initials: same first initial, one list starts the other) and no other entry uses the cited spelling for that person (TulvThom73 `D M Thomson`, editor in Smit88). Either release is reported as `surname_corroborated` (applied) naming the rule, the DOI record rule or the cdl.bib rule. A held name keeps the whole cited name (house format; of several cited authors with that surname, the one at the same position) and the flag names the proposed surname for corroboration or sign-off (README rule; FreeEtal03b keeps `R Jornten`, not Crossref's deposit typo `Jorsten`). The hold is released (`applied`, source `reviewer`) when the reviewer's author verdict confirms it (`agree ...`), and a reviewer's own author value replaces it An author-deposited record fetched from a host the researcher did not quote is a second host (`surname_corroborated`, deposited-record rule): the arXiv record (export.arxiv.org) of an arXiv id named in the row whose title is the entry's (CaliVita05: arXiv cs/0412098 `Rudi Cilibrasi`, key CiliVita07), and the zenodo.org record of the entry's 10.5281/zenodo DOI (ChanEtal20 `Geerligs, Linda`). The Zenodo record carries the same author-entered deposit as its DataCite record: it counts because authors enter their own names there, not because it is independent of DataCite |
| US addresses | normalisation, `us_address_state_unknown` | `City, United States`/`USA`, `City, NJ`, `City, N.J.`, `City, Texas` -> `City, {ST}`; the city's state comes from cdl.bib's own `City, {ST}` addresses, then a small table of unambiguous cities; other addresses go through the house address formatter A different publisher (no content word in common, ignoring Press/Sons/Verlag...) next to a current address that is held or has no confirmed/corrected value is held with it as one decision (`publisher_address_held`: Herb34's 1891 Langensalza publisher and 1834 Königsberg address) |
| Ordinals | normalisation | Numeric ordinals in text fields -> `N\textsuperscript{st/nd/rd/th}` with the correct suffix (URLs untouched); editions `Second`/`2nd ed.` -> `2\textsuperscript{nd}` |
| Issue ranges, pages | normalisation | `3-4` -> `3--4`; page ranges `start--end`, abbreviated end pages expanded (`347-76` -> `347--376`) |
| Proceedings booktitle | normalisation | Years removed from proceedings/conference/meeting/NeurIPS booktitles |
| Field names | normalisation | Field names are case-folded (`entrytype`, `EntryType` -> `ENTRYTYPE`; `Journal` -> `journal`) in researcher rows, reviewer values and verdicts, and validation rows, so a lowercase `entrytype` is the type change (AllpEtal94) |
| Entry types | normalisation, `invalid_entrytype` | `@conference` -> `@inproceedings`; a titled chapter (`@inbook` with a chapter title, or with a booktitle) -> `@incollection` with title = chapter, booktitle = book; an ENTRYTYPE that is not a BibTeX type (a sentence) is dropped `@conference` becomes `@inproceedings` only when its booktitle (or journal) is a proceedings (`PROCEEDINGS_RE`); otherwise `@misc` with `conference_without_proceedings` for the user (Laks01, a speech). The titled-chapter move keeps the researcher's (or reviewer's) corrected title as the chapter title and takes the cited chapter field only when there is none (GoldEtal08, Howa08, BoraEtal05; a title taken from the chapter field is labelled source `postcheck`); when the researcher's booktitle is the cited chapter field, the chapter field is the book and becomes the booktitle (the swap of Stey01, BairNoma78). A contained type never loses its last venue: when the proposed booktitle is held or dropped, the type change and the journal removal are held too (`venue_held`: GatyEtal16, IsolEtal17, LiEtal24a) |
| @book, @article | normalisation | `@book` has no pages; `@article` has no publisher (listed under removals) |
| Article number | normalisation | When pages changes to a single article number and `number` holds the same value, `number` is removed (Brig12, JayaEtal23, CookEtal16, AfshEtal13, NastEtal18). A different issue number stays (FoxGrei10's 10 against article 19) |
| @misc | normalisation | `@misc` has no journal, and a `volume` holding a URL is removed (Hint12's Class Central link); a plain volume stays |
| Researcher removals | normalisation | A row's top-level `"remove": [field, ...]` is honoured: the fields go (listed under removals), unless the reviewer supplied a value for one. A journal on the list is never moved to booktitle or series by the contained-type rule (NeweRose81: `Journal of Mathematical Psychology` ended as its series) |
| No journal on contained types | normalisation | `@inproceedings`/`@incollection`/`@inbook` have no journal (listed under removals): dropped when the booktitle or series already gives it (NeurIPS, SchaTurk15, MayeEtal92b), moved to booktitle when there is none, moved to series when the booktitle differs and there is no series (a book series given as the journal), but dropped when the journal names the same venue as the booktitle (`same_venue`: at least two content words, 80% of them in the booktitle, ignoring function words and generic venue words such as proceedings/annual/conference; DesaEtal12, BoseEtal92). A volume that is the series number already printed in the booktitle (`Attention and Performance {XV}`, volume 15) is removed too |
| House formatters | normalisation, `booktitle_case` | Title, journal and publisher go through `helpers.format_title`/`format_journal_name`; output that alters brace-protected text or lowercases an inner capital (O'Reilly) is rejected |
| Spacing-only change | `style_only_change` | A title/booktitle/journal change that differs only in whitespace (EngeFrie10 `--- signalling`) is a house-style question, flagged |
| Verdicts | `verdict_inconsistent`, `verdict_understated`, `needs_user` | `verified` with a corrected field; `correction` with none; `ambiguous`/`no_source` although identity is quoted and every field confirmed |
| Reviewer merge | `reviewer_dropped`, `reviewer_disagrees`, `reviewer_action` | Each `suggested_value` (every wave's `review.json`: waves 1, 2 and 3) replaces the researcher's value (source `reviewer`) and releases a quote-check hold on that field; a null/empty suggestion withdraws the researcher's change (never an empty value); a field the reviewer disagrees with (`disagree`, `disagree: ...`) and gives no value for is held. A field held only because the validator could not read the source (every failure a fetch failure, or the whole page failed: identity and all fields `quote not found`, as with Project Euclid's block page) is applied with source `reviewer` when the reviewer's verdict confirms it (`agree ...`, `disagree (held but correct)`); a quote that fails on a page that was read (Hint84 volume) is not released this way. The reviewer's `key` is compared with the computed key plan (`reviewer_agrees`) A suggested value `remove` (or `delete`) is an instruction: the field is removed, never set to the word (AbdeEtal21's `force`) |

| Software releases (user rule, 2026-09-26) | `software_first_version`, `software_first_version_authors`, `software_first_version_unresolved`, `software_version_removed` | Software is cited by its FIRST version, with the first version's year and no version number. For a Zenodo DOI (proposed or already in the entry), `zenodo.org/api/records/<id>` gives the release series (`conceptrecid`; a concept DOI redirects to its latest version) and the record whose `relations.version` index is 0 is the first (paged through `/versions`, 25 per page): its DOI replaces the cited one after a registration check and its `publication_date` year replaces the year, which renames the key (MuelEtal18 -> MuelEtal16). A first version whose creator list differs from the entry's is flagged, the authors are left for the user. The version number is removed from the title and note of a software entry (Zenodo DOI, `@software`, or `@misc` pointing at GitHub) and a `version` field is removed (`strip_version`: a trailing `{v0.2.1}`, `v0.2`, `: {Version 1.0}`, Zenodo's `(August, 2023)`, or a dotted version before a colon; not `Llama 3` or `{V1} alpha`). In the DOI title check of a Zenodo DOI, versions are not part numbers (CapoEtal17's `Brain Imaging Analysis Kit v0.2` is the entry's title) |
| Countries in addresses (user rule, 2026-09-26) | `country_dropped` | A country at the end of an applied address (a name such as `Germany`, `UK`, `England`, or a braced non-US code such as `{UK}`, `{FR}`, `{AT}`; `{IN}`, `{LA}`, `{DE}` are US states) that no quote of the address or publisher prints (as the country, its English name or `England`/`Britain` for the UK) is dropped: `Langensalza, Germany` -> `Langensalza` (Herb34), `Heidelberg, Germany` -> `Heidelberg` (BuzsEtal94), `London, {UK}` -> `London`. A quote-check hold whose only missing words are that country is released without it (BuzsEtal94). An address that is only a country is left out. The house address key does not add one back (`Leipzig` stays, not `Leipzig, Germany`). A printed country stays (Rayp68 `Horn, {AT}` from `Horn, Austria`; Addi02 `Bristol, UK`; Smit88 `Chichester [England]`). Addresses nobody proposed or confirmed are not touched |
| User decisions (2026-09-26) | `user_decision`, `user_evidence_unverified` | `crosswave/applied-decisions.json` (the user's answers on the cross-wave page, raw rows in `crosswave/decisions/`) is read in the final pass only, never the rules-alone pass. Per key: `set` values are source `user` (with their own quotes, fetched and checked, else the researcher's evidence for the same value) and supersede holds on those fields; `withdraw` drops research proposals; `resolves_verdict` clears an ambiguous verdict's `needs_user`; `key` fixes the key plan; `merge_into`/`keeper_of` confirm a duplicate (the plan is overridden, with a note, if the post-check planned otherwise); `drop_suffix_if_only` renames a keeper to its base key when no other key with that base is in HEAD cdl.bib; `remove_entry` marks the entry for removal (listed in `crosswave/removals.json`, written by `postcheck.py --write-removals`); `not_abstract` and `names_as_printed` are recorded. `postcheck.json` summary: `user_decisions`, `remove_entries`, `software_first_version`, `country_dropped`; `merged.json` rows: `remove_entry`, `user_decisions` |
| Resolution decisions (2026-09-26) | `resolution_decision`, `resolution_set_refused`, `resolution_quote_unverified`, `resolution_noop`, `resolution_key_collision` | `verification/resolution-2026-09-26/batch-NN.json` (schema in its `BRIEF.md`) is read in the final pass only, after the user's cross-wave decisions, and overrides researcher, reviewer and user values for the fields it touches (source `resolution`). `apply`: each `set` value needs a URL and verbatim quote (else refused) and goes through the house rules (names, pages, booktitle, address, DOI, title and journal form; em dash `a---b`); `withdraw` keeps the bibliography's value; `remove` removes the field; `entrytype`, `new_key`, `merge_into` as given. `drop`: `remove_entry` = `drop_reason`. `keep`: no change at all. The entry's `needs_user` is its residue only (see below) |

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

## Wave 4 and wave 5 review fixes (2026-09-26)

The wave-4 reviewer (88 reviewed, random-sample error 3.6%) and the wave-5 reviewer found
post-check defects. Fixed, each with a regression test on the real row and a negative
control (`tests/test_research_postcheck.py`, wave-4 and wave-5 sections):

- Names: an unbraced capitalised particle became an initial and the surname hold kept it
  (VogtEtal14 `B A L D Leone`); now `B A L {Di Leone}`, not held. A run-together surname
  follows cdl.bib's form for the same author (MillEtal07d `M {den Nijs}`).
- NeweRose81: the researcher's `remove: [journal]` wins over the journal-to-series move.
- DOI title check: correct DOIs no longer dropped for a book-review record (Mitc09), a
  numeral for a number word (Waug63b), a glued italic name (WehnSrin81), a pre-colon
  registry title (Eich04, SaliThie00, ShadMovs99, WagnEtal01), a section numeral (Turi50),
  a one-letter registry typo (ChabEtal98). The part-number guard is live again: it was
  bypassed by the bare word-overlap test; a part-number difference is held unless the first
  page agrees (DamiEtal99a/b, JacoEtal98 applied with a flag).
- HTTP 429/503: retried with backoff and Retry-After before a DOI or quote is held.
- Surname hold: the fetched DOI record is a second host (ToluEtal12, VanEEtal01, and several
  wave 1-5 holds, e.g. YeoEtal11 Polimeni, SerrEtal03 Hatsopoulos, AguiEtal96 D'Esposito);
  suffix damage, split artefacts and restored accents are not respellings (KrauEtal13,
  ChamEtal03, WagnEtal01); an expanded `and others` list is not compared name by name
  (YangEtal24, whose Lin/Dang authors were replaced by cited Li/Yang names).
- `bibcheck/helpers.format_journal_name` no longer applies the journal-key alias that cut
  `-Paris` from `Journal of Physiology-Paris` (LachEtal03); no other formatted journal name
  in cdl.bib or in the journal key changes.

## Wave 6 review fixes (2026-09-26)

The wave-6 reviewer (104 reviewed; random-sample error 16.7%, 2.1% without the post-check's
journal aliases and surname holds) found these post-check defects. Fixed, each with a
regression test on the real wave-6 row and a negative control (`tests/test_research_postcheck.py`,
wave-6 section):

- DOI title check: Curr99, BousRosn70 and Mart65 keep their DOIs (`doi_title_near`). The
  near-title test needs all four of first-author surname, year, volume and first page to
  agree; with any one changed, or with different wording (`Free versus cued recall`), a part
  number, or a title under 20 letters, the record is still another work. BoddEtal97 is still
  dropped.
- TrulEtal97: `Jean-{A}rcady` was read as `J-{` (the brace taken as an initial), so the
  surname looked changed; now `J-A`, and `J.-A.` is `J-A` (it was `J A`). No hold.
- Surname holds: TulvThom73 is released by the cdl.bib rule (`D M Thomson` in Smit88; no
  other entry has `D M Thompson`). Trop86 (`Trope`), CrosEtal93 (`Crosson`) and ParkEtal13
  (`Ghosh`) stay held: each rests on one host (the Crossref record the researcher quoted is
  the record the post-check fetched, so the DOI record rule cannot count it twice; ParkEtal13
  has PMLR only and no DOI), and cdl.bib has no other entry for those people (`K K Ghosh` is
  someone else). Releasing Crossref-only respellings would also release FreeEtal03b's
  deposit typo `Jorsten`. They need a second source or the user's sign-off.
  The cdl.bib rule would also release AguiEtal96 `D'Esposito` and ToluEtal12 `Changeux` without
  their DOIs (cdl.bib writes both elsewhere); the older one-host tests now run on the
  bibliography without those entries, so they still test the hold.
- Print year: WiggEtal99 (January cover date, Crossref 1998-10) and AdelEtal95 (Karger's
  2008 online digitisation date in the notes) no longer suggest a year.
- Journal names: `Psychonomic Science` (BousRosn70, AlleGart68) and `Physiological Reviews`
  (DanPoo06, Jeff95) are kept; the alias fix itself is in `bibcheck/journal_key_overrides.json`
  (3eb4564), the post-check only has a regression test.

## Wave 7, 8 and 9 review fixes (2026-09-26)

The independent reviews of waves 7-9 (`wave7/review.json`, `wave8/review.json`,
`wave9/review.json`, `_summary.systematic_findings`) found these post-check defects. Fixed,
each with a regression test on the real row and a negative control
(`tests/test_research_postcheck.py`, wave-7/8/9 section):

- Titled-chapter move: the researcher's corrected title is the chapter title (GoldEtal08
  `Neural integrator models`, Howa08 `Memory: computational models`, BoraEtal05's serial
  comma); a chapter field that holds the book becomes the booktitle, never the title
  (BairNoma78, Stey01); `no_source` rows are never changed by any post-check rule, and on an
  `ambiguous` row the move is left for the user.
- Ambiguous rows: title, year, DOI, journal and booktitle are held together (Ebbi85).
- Duplicates: RuggAlla00 stays and Rugg00 merges into it; circular plans are impossible.
- Keys: ChatGPT is kept (no key-determining field changed).
- Herb34: publisher and held address are one decision.
- DOI title check: Sand80 (leading chapter number), GusmEtal14 (®/™), HernEtal00 (glued HTML
  tags, Greek letter), LismIdia95 (`\pm`) and Rebe10 (generic column title with volume, issue,
  first page, year and journal agreeing) keep their DOIs; Thor13's existing DOI is no longer
  reported as dropped.
- GatyEtal16, IsolEtal17, LiEtal24a: with the booktitle held, the entry stays an @article
  with its journal (`venue_held`) instead of a venue-less @inproceedings.
- Surname holds: CaliVita05 (arXiv) and ChanEtal20 (Zenodo) are released by the
  deposited-record rule; CaliVita05's key plan becomes CiliVita07.
- `other_version_named` (TsitEtal19, LiEtal24b, JainHuth18) makes `needs_user` true.
- `Force` is removed (AbdeEtal21, LiEtal24b, Amer23b, ChatGPT); a reviewer's suggested value
  `remove` removes the field instead of becoming its value.
- Names: `A Quattrini Li` is no longer `A Q Li` (CarvEtal22b, TianEtal20b), and SingEtal24's
  names stay as the researcher left them.
- Print year: ReccOKee89 (`pre-2000`) and the NeurIPS/Curran reprint years (VaswEtal17,
  LiuEtal18) are no longer print-year conflicts.
- Laks01: `@conference` without a proceedings booktitle becomes `@misc`, flagged.

The waves are re-run by the orchestrator, not by this change.

## Cross-wave user decisions (2026-09-26)

The user answered the cross-wave decisions page (`crosswave/review.html`; answers in
`crosswave/decisions/`, summary in `verification/resolution-plan-2026-09-22/README.md`).
The post-check now applies them, each with a regression test and a negative control
(`tests/test_research_postcheck.py`, cross-wave section):

- Software (`q-brainiak`: "always cite the *first* version (and use to get the year)-- and don't
  specify a version number"): 8 wave entries have a Zenodo DOI. First-version DOI changes:
  MannEtal23b 10.5281/zenodo.8274025 -> 8152316 (v0.1.0, 2023), MuelEtal18 1322068 -> 49907
  (1.2.1, 2016; year 2018 -> 2016, key MuelEtal16), ChanEtal20 and Mann21c concept DOIs 3937848 ->
  3937849 and 5136794 -> 5136795. CapoEtal17 keeps 59780 (v0.2 is the only and first version; now
  applied, year 2016, key CapoEtal16). FitzEtal25, Mann21b, Mann21d are already their first
  versions. Versions removed from titles: FitzEtal25, MannEtal23b, ChanEtal20, MuelEtal18. The first
  version's creators differ from the entry's for MannEtal23b, MuelEtal18 and ChanEtal20
  (`software_first_version_authors`, left for the user). GitHub-only `@misc` entries without a
  DOI or version (Depo18, Eust19, Varo10, Scav05, deCa05a) are not dated by a first release: no
  source for it was fetched.
- Countries (`q-country`: drop): 26 entries lose a country no quote prints (Herb34, BuzsEtal94,
  Frie06, BancEtal65's `{FR}`, and 22 `{UK}` addresses such as `London, {UK}` from a quote `London`).
- Per entry: Ebbi85 is the 1885 German original (`{\"{U}}ber das {G}ed{\"{a}}chtnis: {U}ntersuchungen
  zur experimentellen {P}sychologie`, Duncker \& Humblot, Leipzig, 1885; quotes checked at
  archive.org record berdasgedcht00ebbi; the 1913 translation's title, DOI and year are withdrawn).
  OGra11 year 2008, key OGra08. Shim94 -> Shim95b, Shim95 -> Shim95a (wave 2). BenaEtal04's book
  title (booktitle) `{Youmans} Neurological Surgery`. BeckEtal09, CronEtal94, MannEtal97,
  PailEtal00, SpieEtal18, TongEtal95 are real articles, not abstracts. The 9 approved duplicates
  match the post-check's own merge plans. KahaEtal08b merges into KahaEtal08a, which keeps its
  suffix because KahaEtal08c (a different 2008 paper) is in HEAD cdl.bib. Hwang: printed names
  kept (DankEtal08, HwanEtal05, JacoEtal06, vanVEtal05; no unification).
- Removals: `crosswave/removals.json` lists the 45 approved conference abstracts (JohnRedi07b is
  one of them, also answered as `j-JohnRedi07b`); cdl.bib is not edited.
- Herb34's rules-alone publisher/address hold no longer happens (its address quote check failed
  only on the unprinted country); the held-address case is tested with a quote check that fails on
  the city.

## Resolution decisions (2026-09-26)

The resolution agents (`verification/resolution-2026-09-26/BRIEF.md`) decide every entry the
waves left unresolved. `postcheck.py <wave>` reads their `batch-*.json` from
`verification/resolution-2026-09-26/` by default when the directory exists (`--resolutions
DIR` for another directory or file, `--no-resolutions` to leave them out); `run()` reads
none unless it is given `resolutions=` (a directory, a file or a `{key: row}` dict). A batch
that is not valid JSON, a row whose decision is not apply/drop/keep, or a key decided two
ways in two batches stops the run (`ValueError`): a half-written batch is never read as "no
decision". Like the user's cross-wave decisions they are not rules: the rules-alone pass never
sees them.

Per key (source `resolution`, flag `resolution_decision`):

- `apply` starts from the post-check's final changes. Each `set` value replaces the research
  value and supersedes its hold. Its quote is checked with the research validator's matching
  (`verification/research-pilot-2026-09-24/validate.py`, imported: `check` for the quote at its
  URL, cache first under `.bibcheck/research-pilot/`, then `value_supported` for the value's
  words in the quote); `--offline` never fetches an uncached URL, and NCBI requests are paced to
  at most one per second. A value without a URL or quote is refused (`resolution_set_refused`,
  held). A quote that fails is `resolution_quote_unverified`: held, unless the row's notes say
  the page was read in a browser or transcribed from a scan (the user accepted both, resolution
  plan README round 2), when it is applied with the flag. Set values run through the same house
  rules as any other value (no name suffixes, initials, pages, booktitle, address, DOI, title,
  journal and publisher form) plus the em-dash rule `a---b` for titles and booktitles; the
  resolution's title is the chapter title in the titled-chapter move (Howa08). `withdraw`
  keeps the bibliography's value (or its absence), `remove` removes the field (listed under
  removals; a removed journal is never moved to booktitle or series), `entrytype` is the type.
  After every rule, a set value that did not survive (a DOI dropped by the registry check, a
  booktitle held with its type) is residue; held flags on the fields the resolution set,
  withdrew or removed are dropped as superseded; any other held flag is residue.
- `drop` marks `remove_entry` with the `drop_reason` (summary `resolution_removals`;
  `postcheck.py --write-resolution-removals` writes the list, with the no-ops apart, to
  `removals.json` in the resolution directory, like `crosswave/removals.json`). A drop of a key
  that is not in the bibliography, or that `verification/key-deletions.json` lists as already
  deleted, is a no-op (`resolution_noop`, summary `resolution_noops`): KahaEtal08b and
  JacoEtal05b were deleted and their keys now name other works renamed into them
  (`key-renames.json`), so they are never removed again. With `merge_into` the key plan is also
  a merge.
- `keep` changes nothing: the entry is exactly the bibliography's, the key is kept, held flags
  are superseded. A duplicate the post-check found is residue.
- `merge_into` makes the key plan a merge into that key (residue when it is neither in the
  bibliography nor another entry's planned key). `new_key` is checked against the bibliography's
  keys and every other planned key of the run: the post-check's own plan is confirmed; a free
  key is a rename; a key held by the same work is a merge (residue); a key held by a different
  work gets the next free suffix by the house rule (an unsuffixed holder becomes `a`), reported
  as `resolution_key_collision` (summary `resolution_key_collisions`). A final key that does
  not follow the ID rule for the corrected metadata is residue. Planned keys of other waves
  are not visible to one wave's run.
- A key the bibliography has renamed since the resolution was written (`key-renames.json`,
  e.g. the wave-1 apply's HerrEtal10 -> HerrEtal10a, Adey67a -> Adey67, Frie08 -> Frie08a) is
  followed along the rename chain to its current key (`follow_renames`), and the decision is
  checked and applied there: the entry is checked under the current key, its key plan starts
  from it, and a drop removes it under that key (`renamed_from` in `removals.json`). Each
  redirect is flagged `resolution_redirect` and listed in summary `resolution_redirects`
  (`from`, `to`, `chain`, `decision`). A key listed in `key-deletions.json` is never followed
  from (KahaEtal08b, JacoEtal05b: deleted, suffix reused), a cycle (SilvEtal19's
  self-replacement) stops the walk, and a chain that ends outside the bibliography is no
  redirect. `run(..., renames=)` takes the ledger (default `key-renames.json`).
- A key not in the bibliography (and not renamed): every decision is a no-op; an `apply` with
  changes is residue.

An entry with a resolution needs the user only for its residue (`resolution.residue` in
`merged.json`, summary `resolution_residue`); its verdict is resolved. Tests
(`tests/test_research_postcheck.py`, resolution section; real rows frozen in the test, the
pre-wave-1 bibliography fixture, an empty deletion ledger unless the test gives one): BairNoma78
(apply with set, withdraw, remove, entrytype), Howa08 (title over the chapter move, key
confirmed), GoldEtal08 (house names), Seac97 (drop), DaPo67 (keep), WhitEtal96 (merge), KahaEtal08b
(drop of a deleted, reused key), Frie08 (apply followed to its renamed key Frie08a through
`run()`, with frozen `key-renames.json` rows); negative controls: without the rename ledger the
Frie08 decision is a no-op, a deleted key is never followed, a set without a quote is refused, a failing
quote holds unless the notes say browser or scan, a drop of an absent key is a no-op, a new key
held by another work or planned by another entry collides, a missing merge target is residue,
and unreadable batches stop the run.
