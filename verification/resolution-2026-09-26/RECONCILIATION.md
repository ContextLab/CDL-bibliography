# Reconciliation of resolution batches against the final rules (2026-09-26)

Scope: batches 01-17, 19, 20, 23, 24, 25, 26 (not 18, 21, 22). Every entry was re-read against the
final rules in `verification/resolution-plan-2026-09-22/README.md` (standing rules, round-1 and round-2
answers, Claude's defaults and the reconciliation notes) and `BRIEF.md`. Each changed entry's `notes`
now ends with a `RECONCILED 2026-09-26:` sentence giving the rule and evidence. The files stay valid JSON
in the BRIEF schema (rewritten with `indent=1`, UTF-8).

## Decision counts (458 entries)

| | apply | drop | keep |
|-|-|-|-|
| before | 399 | 47 | 12 |
| after | 397 | 55 | 6 |

Moves: keep -> drop PailEtal00, MannEtal97, McGi63, Crai77; apply -> drop KaneHash95, CronEtal94,
WhitEtal96, Wayn96; keep -> apply DaPo67, Yone96.

## Decisions worth reading first

- **JacoEtal05b, KahaEtal08b stay `drop`, as NO-OPs.** The queued works are already deleted, and both
  keys now name different works in HEAD (key-renames.json: JacoEtal05d -> JacoEtal05b, Jacoby et al.
  2005 JML; KahaEtal08c -> KahaEtal08b, Kahana et al. 2008 Psych Rev). I first changed them to `keep`,
  then reverted. postcheck.py's `apply_resolutions` and `build_resolution_removals` already treat a
  drop of a key listed in key-deletions.json as a no-op ('the key now names another work ... not
  removed'), whereas `keep` would add a residue item. Each note now says an applier must NOT delete
  the HEAD entry. (HEAD KahaEtal08b also has `{R}eply` after a colon and no DOI; it was not reviewed
  here.)
- **NeurIPS years:** the conference year applies everywhere. SanbGrif08 -> SanbGrif07 (NIPS 20 =
  2007, same as RaoHowa07 in batch 24). MairEtal09b -> MairEtal08 and MnihHint09 -> MnihHint08
  (NIPS 21 = 2008). The NeurIPS site prints `citation_publication_date` 2007/2008. AlvaEtal05 changes
  from @article to @inproceedings, the form every other NeurIPS entry in these batches uses.
- **Queue keys renamed in HEAD** (key-renames.json): HerrEtal10 is now HerrEtal10a, Adey67a is now
  Adey67 and Frie08 is now Frie08a. An applier has to map each queued key to its current name.
- **Side effects of new keys** (house suffix rule; not edited here): once MairEtal09b becomes
  MairEtal08, HEAD MairEtal09a is the only MairEtal09 left. Once deCa05a becomes deCa04, deCa05b is
  the only deCa05 left.

## Changes

| Key | Batch | Change | Rule | Evidence |
|-|-|-|-|-|
| ChanEtal09a | 01 | no field change; question answered | NeurIPS default | (see batch notes) |
| HillEtal87 | 01 | journal -> full bilingual title | Bilingual journal titles: full title (default) | https://comportements.ch/en/journal-architecture-behaviour-2/ |
| MairEtal09b | 01 | year -> 2008; new_key MairEtal08 | Proceedings year = conference year (NeurIPS default) | https://proceedings.neurips.cc/paper_files/paper/2008/hash/c0f168ce8900fa56e57789e2a2f2c9d0-Abstract.html |
| MairEtal09b | 01 | no field change; question answered | NeurIPS default | (see batch notes) |
| MnihHint09 | 01 | year -> 2008; new_key MnihHint08 | Proceedings year = conference year (NeurIPS default) | https://proceedings.neurips.cc/paper_files/paper/2008/hash/1e056d2b0ebd5c878c550da6ac5d3724-Abstract.html |
| MnihHint09 | 01 | no field change; question answered | NeurIPS default | (see batch notes) |
| PaszEtal19 | 01 | no field change; question answered | NeurIPS default | (see batch notes) |
| RendCrai00 | 01 | pages S43--S62 set with publisher evidence | Unconfirmable optional fields -> remove unless confirmed (confirmed) | http://web.archive.org/web/20220709200648/https://onlinelibrary.wiley.com/doi/abs/10.1002/acp.770 |
| SanbGrif08 | 01 | year -> 2007; new_key SanbGrif07 | Proceedings year = conference year (NeurIPS default) | https://proceedings.neurips.cc/paper_files/paper/2007/hash/89d4402dc03d3b7318bbac10203034ab-Abstract.html |
| DelbBeau89 | 02 | journal change withdrawn; number 'Suppl 1'; volume removed | Supplements: parent journal, Number as printed (default) | https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=2757728,2757730&rettype=medline&retmode=text |
| EichEtal92 | 02 | no field change; question answered | em dash a---b | (see batch notes) |
| HerrEtal10 | 02 | note only: HEAD key is now HerrEtal10a | Key renames | verification/key-renames.json |
| KeriEtal07 | 02 | no field change; question answered | Supplements default | (see batch notes) |
| PoitEtal89 | 02 | journal change withdrawn; number 'Suppl 1'; volume removed | Supplements: parent journal, Number as printed (default) | https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=2757728,2757730&rettype=medline&retmode=text |
| CronEtal94 | 03 | apply -> drop | Collective 'Abstracts' record -> drop (default) | https://api.crossref.org/works/10.1006/brln.1994.1057 |
| Gomu53 | 03 | pages 1--91 -> 1--94 | Unconfirmed optional field replaced by catalogue extent (cross-batch consistency with Gate17) | https://www.loc.gov/item/53011675/?fo=json |
| KojiGold82 | 03 | pages 43--49 -> 43--50 | Conflicting records: Crossref beats PubMed (round 1) | Crossref |
| McCuPitt43 | 03 | no field change; question answered | Author names (round 1) | (see batch notes) |
| Buse01 | 04 | no field change; pages now evidenced by contents list (question cleared) | Chapter pages: start page confirmed -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts |
| Hara96 | 04 | no field change; pages now evidenced by contents list (question cleared) | Chapter pages: start page confirmed -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts |
| PribEtal74 | 04 | editor added (4 editors) | 'and others' expansion; cross-batch consistency with AtkiJuol74 | https://escholarship.org/content/qt40x8f9s7/qt40x8f9s7.pdf |
| Sate14 | 04 | no field change; question answered | em dash a---b | (see batch notes) |
| BabiEtal08 | 05 | author 'and others' -> full 14-author list | 'and others' expansion (default) | https://api.crossref.org/works/10.1002/hbm.20648 |
| DaPo67 | 05 | keep -> apply: @phdthesis, school Indiana University, year 1966, new_key DaPo66; remove journal/volume/pages | DAI -> @phdthesis (round 2) | https://iucat.iu.edu/catalog/617689/librarian_view |
| Half88 | 05 | no field change; question answered | end page from next start - 1 (round 2) | (see batch notes) |
| Hass05 | 05 | no field change; question answered | em dash a---b | (see batch notes) |
| PetrPand94 | 05 | no field change; question answered | end page from next start - 1 (round 2) | (see batch notes) |
| Yone96 | 05 | keep -> apply: @phdthesis, school McMaster University, year 1995, DOI 10.71548/12410, new_key Yone95 | DAI -> @phdthesis (round 2) | https://prod-ms-be.lib.mcmaster.ca/server/oai/request?verb=GetRecord&metadataPrefix=oai_dc&identifier=oai:macsphere.mcmaster.ca:11375/6990 |
| Madi71 | 06 | no field change; question answered by author-name rule | Author names (round 1) | (see batch notes) |
| PfurEtal96 | 06 | title withdrawal cancelled (post-check 'a---b' title applies) | Em dash a---b | (see batch notes) |
| TulvHast72 | 06 | no field change; question answered by author-name rule | Author names (round 1) | (see batch notes) |
| WhitEtal96 | 06 | apply -> drop (merge_into kept) | Cross-batch consistency: already-deleted duplicates are drop + merge_into | (see batch notes) |
| YoneJaco97 | 06 | title keeps quotation marks ``...'' | Title quoting another title: ``X'' (default) | https://api.crossref.org/v1/works/10.1037/0096-3445.126.1.18/transform/application/vnd.crossref.unixsd+xml |
| Bull90 | 07 | no field change; question answered | browser-read PsycNET pages accepted (round 2) | (see batch notes) |
| ZhanEtal06 | 07 | title withdrawal cancelled (post-check 'a---b' title applies) | Em dash a---b | (see batch notes) |
| BurgShal96 | 08 | no field change; question answered | publisher/Crossref beats PubMed (round 1) | (see batch notes) |
| ChabEtal98 | 08 | no field change; question answered | Title misprint default | (see batch notes) |
| DuchNeel89 | 08 | no field change; question answered | 'X' multiplication sign -> $\times$ (default) | (see batch notes) |
| Gree08 | 08 | editor J H Byrne -> volume editor | Multi-volume work: Editor = volume editor (default) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=3&recordSchema=marcxml&query=dc.title%3D%22learning%20and%20memory%20a%20comprehensive%20reference%22 |
| JacoEtal98 | 08 | no field change; question answered | subtitle after a period -> colon (default) | (see batch notes) |
| Merk14 | 08 | volume 2014 removed | ACM 'Volume <year>' -> omit (default) | (see batch notes) |
| Turi50 | 08 | no field change; question answered | roman volume -> arabic (default) | (see batch notes) |
| VossPall08 | 08 | editor J H Byrne -> volume editor | Multi-volume work: Editor = volume editor (default) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=3&recordSchema=marcxml&query=dc.title%3D%22learning%20and%20memory%20a%20comprehensive%20reference%22 |
| Wayn96 | 08 | apply -> drop (merge_into kept) | Cross-batch consistency: already-deleted duplicates are drop + merge_into | (see batch notes) |
| HughEtal00 | 09 | no field change; question answered | publisher/Crossref beats PubMed (round 1) | (see batch notes) |
| KingEtal11 | 09 | no field change; question answered | person + corporate byline: key from authors2key (default) | (see batch notes) |
| NadeEtal00 | 09 | J E {Le Doux} -> J E LeDoux | Author names: correct, most complete name (round 1) | PubMed 10845062 |
| TrenEtal93 | 09 | author withdrawal cancelled (Jr dropped) | No name suffixes (house rule) | (see batch notes) |
| Adey67a | 10 | note only: HEAD key is now Adey67 | Key renames | verification/key-renames.json |
| BunnEtal99 | 10 | no field change; question answered | image-only scans accepted (round 2) | (see batch notes) |
| GrunSher01 | 10 | no field change; question answered | society proceedings: printed year of the bound part (default) | (see batch notes) |
| Maha36 | 10 | no field change; question answered | image-only scans accepted (round 2) | (see batch notes) |
| BousRosn70 | 11 | title -> 'Free vs uninhibited recall' | Title misprint: correct spelling with evidence (default) | https://web.archive.org/web/20230412122458/https://link.springer.com/article/10.3758/bf03335608 |
| Dall65 | 11 | no field change; question answered | Round-1 precedence | (see batch notes) |
| DelaEtal10 | 11 | no field change; question answered | Author names (round 1) | (see batch notes) |
| FrenDoub74 | 11 | no field change; question answered | em dash a---b | (see batch notes) |
| LaVoLigh92 | 11 | no field change; question answered | Author names (round 1) | (see batch notes) |
| ShapPale70 | 11 | no field change; question answered | Author names (round 1) | (see batch notes) |
| ShifStey97 | 11 | no field change; question answered | em dash a---b | (see batch notes) |
| UnswEtal09 | 11 | no field change; question answered | em dash a---b | (see batch notes) |
| Wick69 | 11 | no field change; question answered | Author names (round 1) | (see batch notes) |
| EggeEtal07 | 12 | no field change; question answered | reprint not found -> original (default) | (see batch notes) |
| JacoEtal05b | 12 | drop kept; note added: NO-OP, HEAD key names a different work (postcheck treats drop of a key-deletions.json key as no-op) | Drops must not target a key that now names a different work | verification/key-renames.json |
| MannEtal97 | 12 | keep -> drop | Rule 1 beats earlier keeps (round 2) | (see batch notes) |
| PailEtal00 | 12 | keep -> drop | Rule 1 beats earlier keeps (round 2) | (see batch notes) |
| WaszWalt83 | 12 | Waszcak -> Waszczak | Author names: correct, most complete name (round 1) | PubMed 8102308 |
| HerrMeck01 | 13 | no field change; question answered | compound spelling: publisher/Crossref form (default) | (see batch notes) |
| LeCuBeng95 | 13 | no change (pages stay removed); start page 255 found; new question | Chapter pages default | (see batch notes) |
| MurEtal12 | 13 | title withdrawal cancelled (post-check 'a---b' title applies) | Em dash a---b | (see batch notes) |
| Tulv95 | 13 | no field change; pages now evidenced by contents list (question cleared) | Chapter pages: start page confirmed -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts |
| Youn12 | 13 | no field change; question answered | web-only articles (default) | (see batch notes) |
| Jost97 | 14 | no field change; question answered | end page from next start - 1 (round 2) | (see batch notes) |
| Kroh35 | 14 | no field change; question answered | abstracting-index citation alone keeps an entry (round 2) | (see batch notes) |
| MuelEtal18 | 14 | no field change; question answered | software first version title as registered (default) | (see batch notes) |
| MullSchu94 | 14 | pages 257--339 -> 81--190, 257--339 | Article in two parts: both ranges (default) | https://archive.org/download/zeitschriftfurp09psycgoog/zeitschriftfurp09psycgoog_djvu.txt |
| AlvaEtal05 | 16 | @article/journal -> @inproceedings/booktitle, +publisher MIT Press, +editor | Cross-batch consistency (NeurIPS form); NeurIPS year default | https://proceedings.neurips.cc/paper_files/paper/2005/file/b19aa25ff58940d974234b48391b9549-Bibtex.bib |
| NakaEtal92 | 16 | no field change; question answered | a first-page-only record is incomplete, not conflicting (default) | (see batch notes) |
| GoldEtal21 | 17 | bioRxiv preprint -> Nat Neurosci 25(3):369-380 (2022), new_key GoldEtal22 | Preprint vs later article: replace when content confirms (default) | https://www.nature.com/articles/s41593-022-01026-4 |
| LiuEtal24 | 17 | author -> {DeepSeek-AI}; new_key DeepEtal25 -> Deep25 | Organizational byline: organization alone (default) | https://arxiv.org/pdf/2412.19437v2 |
| Ship46 | 17 | @misc PsycTESTS -> @article Shipley 1940 J Psychol (new_key Ship40) | Cited test manual with no record -> original article (default) | https://api.crossref.org/works/10.1080/00223980.1940.9917704 |
| YangEtal24 | 17 | author -> {Qwen Team}; new_key YangEtal25c -> Qwen25 | Organizational byline: organization alone (default) | https://arxiv.org/pdf/2412.15115v2 |
| AtkiJuol74 | 19 | publisher Freeman -> W H Freeman | Publisher initials rule; cross-batch consistency with PribEtal74 | LoC 73021887 |
| Bowe72 | 19 | removal of pages, chapter withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=%22Coding%20processes%20in%20human%20memory%22%20%22VARIABILITY%2C%20Cordon%20H.%20Bower%22 |
| Brin65 | 19 | removal of pages withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=%22Cognitive%20sets%2C%20speed%20and%20accuracy%22 |
| Este72 | 19 | removal of pages withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=%22Coding%20processes%20in%20human%20memory%22%20%22ORGANIZATION%20IN%20MEMORY%2C%20W.%20K.%20Estes%22 |
| John72a | 19 | removal of pages withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=%22Coding%20processes%20in%20human%20memory%22%20%22How%20We%20Characterize%22 |
| KahaEtal08b | 19 | drop kept; note added: NO-OP, HEAD key names a different work (postcheck treats drop of a key-deletions.json key as no-op) | Drops must not target a key that now names a different work | verification/key-renames.json |
| RescWagn72 | 19 | removal of pages withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://books.google.com/books?vid=LCCN72177684 |
| RockCera64 | 19 | removal of pages withdrawn (HEAD range kept) | Chapter pages: start page confirmed by contents list -> keep cited range (default) | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_page=100&user_query=%22Cognition%3A%20theory%2C%20research%2C%20promise%22%20%22cognitive%20theory%20of%20associative%20learning%22 |
| Crai77 | 20 | keep -> drop | Reference-list-only evidence -> drop (default) | (see batch notes) |
| KaneHash95 | 20 | apply -> drop | Reference-list-only evidence -> drop (default) | (see batch notes) |
| McGi63 | 20 | keep -> drop | Reference-list-only evidence -> drop (default) | (see batch notes) |
| Stey01 | 20 | no field change; question answered | encyclopedia print edition (default) | (see batch notes) |
| AdamEtal10 | 23 | no field change; question answered | DAKOTA: cite the user's manual (default) | (see batch notes) |
| BairNoma78 | 23 | no field change; question answered | unconfirmable chapter of a single-author book -> whole book (default) | (see batch notes) |
| BravEtal07 | 23 | no field change; year 2008 confirmed by LoC print imprint (note corrected) | Print year (consistency check) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSchema=marcxml&query=bath.isbn=9780195168648 |
| CannEtal16 | 23 | @techreport -> @misc; howpublished URL; remove institution/type/number | Python PEPs -> @misc (default) | https://peps.python.org/pep-0518/ |
| ChatGPT | 23 | no field change; question answered | descriptive keys -> rule keys (default) | (see batch notes) |
| CoghStuf13 | 23 | @techreport -> @misc; howpublished URL; remove institution/type/number | Python PEPs -> @misc (default) | https://peps.python.org/pep-0440/ |
| Frie08 | 23 | year 2011 -> 2012, new_key Frie11 -> Frie12 | Print year of the printed book (cross-batch consistency) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSchema=marcxml&query=bath.isbn=9780195374148 |
| HallGree08 | 23 | volume 1 added | Volume-numeral page prefix -> Volume (default; consistency with batch 26) | https://api.crossref.org/works/10.4135/9781412964012.n23 |
| HashEtal07 | 23 | no field change; year 2008 confirmed by LoC print imprint (note corrected) | Print year (consistency check) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSchema=marcxml&query=bath.isbn=9780195168648 |
| KaneEtal07 | 23 | no field change; year 2008 confirmed by LoC print imprint (note corrected) | Print year (consistency check) | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSchema=marcxml&query=bath.isbn=9780195168648 |
| Schl07 | 24 | year -> 2000, new_key Schl00 | Software without registered release: earliest printed date (default) | https://sourceforge.net/rest/p/biosig |
| Smit05 | 24 | year -> 2001, new_key Smit01 | Software without registered release: earliest printed date (default) | https://www.ode.org/ |
| Stra06 | 24 | year -> 2001, new_key Stra01 | Software without registered release: earliest printed date (default) | https://sourceforge.net/rest/p/visionegg |
| TorvHama05 | 24 | title/author from first release (GIT: the stupid content tracker; L Torvalds), new_key Torv05 | Software without registered release: first release (default) | https://raw.githubusercontent.com/git/git/e83c5163316f89bfbde7d9ab23ca2e25604af290/README |
| deCa05a | 24 | year -> 2004, new_key deCa04 | Software without registered release: earliest printed date (default) | https://raw.githubusercontent.com/libsndfile/libsamplerate/master/NEWS |
| vanREtal14 | 24 | @techreport -> @misc; howpublished URL; remove institution/type/number | Python PEPs -> @misc (default) | https://peps.python.org/pep-0484/ |
| vond81 | 24 | @techreport 1981 -> @incollection 1994 reprint (new_key vond94) | Internal report known from reference lists -> registered reprint (default) | https://api.crossref.org/works/10.1007/978-1-4612-4320-5_2 |
| WallEtal57 | 25 | no field change; question answered | reference-list-only -> drop (default) | (see batch notes) |
| HuggEtal06 | 26 | no field change; question answered | ICASSP volume prefix -> Volume (default) | (see batch notes) |

## New rule-level questions (not settled here)

1. Does "subtitle after a period -> colon" apply to part numerals (`... analysis. {II}. Event-related ...`,
   `Studies of learning to learn: {VIII}. The influence ...`)? HEAD writes `{II}. ` 31 times and `{II}: `
   9 times. Left unchanged: JaspAndr38, CronEtal98a, DamiEtal99a, KeppEtal68.
2. How should a spaced en dash or hyphen used as a title dash be written (Crossref `Remembering –
   Electroencephalographic`, `Notebooks – a`, `Binder 2.0 - Reproducible`)? As `---` (em-dash rule),
   `--`, or as printed? The current values are inconsistent: VossPall08 uses a closed `--`, while
   KluyEtal16 and RagaWill18 use a spaced ` -- `.
3. Does the ACM "Volume = year -> omit" default also cover publishers whose official volume *is* the
   year (Hindawi, e.g. CookEtal16 volume 2016)? Left unchanged here.
4. In encyclopedic handbooks, articles start mid-page. May the end page equal the next article's
   start page (LeCuBeng95: 255, next 258)? Pages stay removed until this is answered.
5. When Crossref's chapter pages come from a digital edition whose pagination is offset from the print
   book (MIT Press Direct 411-442 against the print 421-452 that every citation gives, AllpEtal94), is
   that a conflict (Crossref wins) or a different edition (keep the print pages, as batch 04 did for
   Buse01's reissue)? AllpEtal94 still keeps 421--452.

## Could not settle (left as written, question kept in the batch file)

- RaskCook37: APA prints "S. A. Cook" on this 1937 paper and also on Cook's 1939 paper
  (10.1037/h0054598, "Stuart A. Cook"). HEAD has "S W Cook". No independent record shows which is
  correct.
- SvenEtal24: the byline reads "Hoang NT" (PubMed LastName "Nt", ForeName "Hoang"). The surname and
  order could not be established, so HEAD "N T Hoang" is kept.
- Kura81: the Physica A subtitle printed in 1981 could not be confirmed.
- MallEtal02: volume derived from the catalogue numbering. vand95: locators versus title (batch 07 q3,
  no rule yet). JaspPenf49: issue number conflict. Gate17/Gomu53: pages of a monograph issue (both now
  use the catalogue extent). Newm08: pages of a reference work with several versions.
- Weic96 stays dropped: no catalogue or index record reachable (OpenAlex search gave no match;
  ProQuest needs a login).

## Notes for files owned by others (not edited)

- batch-18 cites NeurIPS papers as @incollection (ChenEtal15a, MozeEtal09, SkagEtal93). These batches
  use @inproceedings.
- HEAD YangEtal25b (Qwen3 report) lists individuals, while YangEtal24 now follows the
  organizational-byline default, `{Qwen Team}`, as HEAD Qwen26 already does.

## Follow-up (2026-09-26): NeurIPS entry type and the unsettled entries

### NeurIPS/NIPS entry type

Every NeurIPS/NIPS entry in the resolution batches now ends as @inproceedings with Booktitle
`Advances in Neural Information Processing Systems`. HEAD cdl.bib (23 entries) currently has 13
@article/Journal, 5 @inproceedings (plus YangEtal13, a NIPS workshop), 3 @incollection and 1 @conference.
All 13 @article entries are planned as @inproceedings/booktitle by the wave post-checks: wave 2 for
ChanEtal09a, SochEtal09, KrizEtal12, KiroEtal15, PaszEtal19, MairEtal09b, MnihHint09, SanbGrif08,
BorzEtal23b, ShihEtal23, ChenEtal24b, ChenEtal24c and GrifStey03. Wave 9 plans VaswEtal17 as
@conference -> @inproceedings, and batches 16/17 set AlvaEtal05 and JainHuth18 to @inproceedings. After
the planned changes, @inproceedings is the form of every NeurIPS entry except batch 18's three.

| Key | Batch | Change | Rule | Evidence |
|-|-|-|-|-|
| ChenEtal15a | 18 | entrytype @incollection -> @inproceedings (booktitle, editor, publisher, volume unchanged) | Cross-batch consistency (NeurIPS form) | wave-2/7/9 postcheck.json plans; batches 16, 17 |
| MozeEtal09 | 18 | entrytype @incollection -> @inproceedings | Cross-batch consistency (NeurIPS form) | same |
| SkagEtal93 | 18 | entrytype @incollection -> @inproceedings | Cross-batch consistency (NeurIPS form) | same |

No other batch disagrees. The earlier note "batch-18 cites NeurIPS papers as @incollection" is resolved.

### The unsettled entries

| Key | Batch | Outcome | Rule | Evidence |
|-|-|-|-|-|
| JaspPenf49 | 01 | Number = 1 (question closed) | Conflicting official records: publisher page first, then Crossref | https://web.archive.org/web/20251204150514id_/https://link.springer.com/article/10.1007/BF01062488 (`<meta name="citation_issue" content="1"/>`); Crossref deposits `1-2` |
| RaskCook37 | 06 | author stays `E Raskin and S W Cook` (question closed) | Author names: correct, most complete name, evidence from the same author's other records | Crossref: 'Stuart W. Cook' on 10.1037/h0063120 (1936), 10.1080/00224545.1938.9921689 (1938), 10.1176/ajp.95.6.1259 (1939), 10.1037/h0049639 (1940). 'Stuart A.' appears only on APA's 1937-1940 deposits (h0061612, h0063197, h0054598, h0061199) |
| Kura81 | 10 | journal -> `Physica {A}: Theoretical and Statistical Physics` (question closed) | Renamed journals: the name as printed at publication | https://lobid.org/resources/990054575850206441.json (ZDB 189951-X: 'Theoretical and statistical physics ( Sachl. Benennung 79.1975 - 152.1988 )'; 'Statistical and theoretical physics' only for 153.1988-254.1998) |
| MallEtal02 | 08 | Volume 16 stays, now with direct evidence (question closed) | Unconfirmable optional fields are removed; this one is confirmed (an abstracting-index record is accepted, round 2) | https://api.openalex.org/works/W179268414 (`"biblio":{"volume":"16",...,"first_page":"24","last_page":"28"}`); lobid numbering 1.1987; Crossref KI 2010 = volume 24 |
| Newm08 | 13 | batch values stand: print-dated record, pages 4059--4064, 2nd ed., DOI kept (question closed) | Print-edition defaults (encyclopedia; print book vs e-book reissue; offset digital pagination) | Crossref 10.1007/978-1-349-58802-2_1061: published-print 2008, page 4059-4064, ISBN 9781349588022 |
| SvenEtal24 | 12 | NOT settled. HEAD unchanged, new evidence added, question rewritten | see below | https://api.researchmap.jp/hoangnt (self-registered: family_name en 'NT', kana グエンタイ; given 'Hoang'); https://gearons.org/about/ |
| vand95 | 07 | NOT settled. Batch decision (re-point to van der Kolk & Fisler 1995 by its locators) left as written | see below | (batch notes) |

Still needing a rule:

- SvenEtal24: when an author's registered family name is itself initials ('Hoang NT', family 'NT' read
  Nguyen Thai), do we write the surname as printed ('H {NT}', which bibcheck's formatter currently turns
  into the initials 'H N T'), spell it out from the registered reading ('H {Nguyen Thai}'), or keep the
  byline as printed? HEAD's 'N T Hoang' makes 'Hoang' the surname. The author's own record says that is
  wrong.
- vand95: when a citation's journal, year, volume, issue and pages identify one work, but its title and
  author list belong to a different work by the same first author, do the locators win (re-point the
  entry), does the title win, or is the entry dropped?
