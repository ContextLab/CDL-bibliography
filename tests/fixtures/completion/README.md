# Saved source records for the entry-completion tests

`records.json` holds real saved responses, one item per work. Nothing in it was typed by
hand and nothing was fetched for it: every record was copied by `extract_records.py` from a
case file already in `tests/fixtures/`, which stores the Crossref and Europe PMC responses
the citation checker received for entries of `cdl.bib`.

Each item has:

- `doi`: the DOI of the record;
- `origin`: the case file and the case (a `cdl.bib` key) the record was copied from;
- `crossref`: the Crossref work record (`record`), the time it was retrieved
  (`retrieved_at`) and its DOI link (`url`);
- `europepmc` (when the case holds one): the Europe PMC search result for the same DOI
  (`raw_record`), when it was retrieved, its page (`url`) and the request (`request_url`);
- `typed` (one item): the entry as it stood in `cdl.bib` when the case was saved.

The Crossref request URLs are in the `attempts` of each case in the origin file. They are
not copied here because they carry the requester's contact address.

One alteration was made to the records: an e-mail address inside a record's text (PubMed
prints the corresponding author's address in the affiliation) is replaced by
`[address removed]`. Nine strings in six Europe PMC records are affected; no Crossref record is.

| Item | DOI | Copied from | Crossref retrieved | Europe PMC | What it exercises |
|-|-|-|-|-|-|
| `MoheEtal14` | 10.1177/0956797613511257 | pagination_corrections.json, case `MoheEtal14` | 2026-09-09 | PMID 24390823, 2026-09-10 | plain article; title in Title Case at Crossref |
| `Zoll90` | 10.1002/tea.3660271011 | phase0_cases.json.gz, case `Zoll90` | 2026-09-22 | none | print year 1990, online (digitised) 2011 |
| `Game62` | 10.1037/h0041332 | phase0_cases.json.gz, case `Game62` | 2026-09-17 | PMID 13896567, 2026-09-10 | issue stated by Crossref only |
| `KoelEtal16` | 10.1038/srep19741 | phase0_cases.json.gz, case `KoelEtal16` | 2026-09-21 | PMID 26830652, 2026-09-10 | article number; issue stated by Crossref only |
| `AlyTurk16` | 10.1073/pnas.1518931113 | fixes-2026-09-24-cases.json.gz, case `AlyTurk16` | 2026-09-17 | PMID 26755611, 2026-09-10 | pages stated by PubMed only |
| `ChenEtal21` | 10.1016/j.cub.2021.07.061 | machinery-2026-09-25-cases.json.gz, case `ChenEtal21` | 2026-09-25 | PMID 34428470, 2026-09-25 | hyphenated initial, surname particle, pages with an .e suffix |
| `FiedGloc12` | 10.3389/fpsyg.2012.00335 | phase0_cases.json.gz, case `FiedGloc12` | 2026-09-17 | PMID 23162481, 2026-09-10 | accented surname; article number from PubMed; no issue |
| `Schr03` | 10.1007/s00406-003-0438-1 | machinery-2026-09-25-cases.json.gz, case `Schr03` | 2026-09-25 | PMID 14504993, 2026-09-25 | line break inside the Crossref title |
| `PigeEtal12` | 10.4088/jcp.11r07586 | machinery-2026-09-25-cases.json.gz, case `PigeEtal12` | 2026-09-25 | PMID 23059158, 2026-09-25 | issue "09" at Crossref, "9" at PubMed |
| `LindEtal21` | 10.1017/s1355617720001009 | phase0_cases.json.gz, case `LindEtal21` | 2026-09-21 | PMID 33050976, 2026-09-10 | corporate author; print year 2021, online 2020 |
| `Knut07` | 10.1519/r-505011.1 | phase0_cases.json.gz, case `Knut07` | 2026-09-21 | PMID 17685726, 2026-09-10 | pages "973" at Crossref, "973-978" at PubMed |
| `CleeMcCl91` | 10.1037/0096-3445.120.3.235 | apply-2026-09-25-cases.json.gz, case `CleeMcCl91` | 2026-09-17 | none | typed surname McCleeland, source McClelland (the typed entry is stored too) |
| `all-capitals-title` | 10.1146/annurev.neuro.29.051605.112819 | phase0_cases.json.gz, case `Raic06` | 2026-09-09 | none | all-capitals title |
| `corporate-author` | 10.1038/s41592-019-0686-2 | phase0_cases.json.gz, case `HarrEtal20` | 2026-09-09 | PMID 32015543, 2026-09-10 | corporate author; the article has a correction (updated-by); PubMed record not usable |
| `erratum` | 10.1038/s41592-020-0772-5 | phase0_cases.json.gz, case `HarrEtal20` | 2026-09-09 | none | a correction notice (update-to) |
| `book-chapter` | 10.4324/9781315782379-49 | apply-2026-09-25d-cases.json.gz, case `AltmSchu02` | not stored | none | record type book-chapter |
| `preprint` | 10.1101/511782 | fixes-2026-09-24-cases.json.gz, case `AlyTurk16` | 2026-09-17 | none | record type posted-content |
| `sentence-case-proper-noun` | 10.1037/0033-295x.92.1.130 | phase0_cases.json.gz, case `Pike84` | 2026-09-09 | none | sentence-case title with a name ("A reply to Pike.") |

The `book-chapter` record comes from a case file that stores the record without its
retrieval time (its `source` note: `verification/baseline.jsonl.gz at 89c5b70`).

To rebuild `records.json` from the case files: `python tests/fixtures/completion/extract_records.py`.

## `retracted-article.json`

The one record fetched for these tests: no saved case holds an article that was retracted.
It is the Crossref work record of 10.1016/S0140-6736(97)11096-0, whose `updated-by` lists a
correction and a retraction. The response body is saved as returned, with the request URL
(`https://api.crossref.org/works/10.1016/S0140-6736(97)11096-0`, without the contact address
parameter) and the retrieval time (`2026-10-02T18:38:45.960152+00:00`). It was requested once, through
`cdlbib.verification.PoliteClient`.

## `responses.json`

The lookups of `tests/test_complete_identify.py`: 36 responses (23 at first, 13 more for the
first round of fixes, rows 24 to 36), each requested once on
2026-10-02 through `cdlbib.verification.PoliteClient` (one request per second or slower) by
running `cdlbib.complete.propose` on the queries below. Each item has the `request` (the
client's cache key: the URL, the parameters and whether the body is XML; for the arXiv
document, the arXiv check's key) and the `response` exactly as the client cached it: `url`,
`retrieved_at`, `http_status` and `body`.

The body is what the client keeps, not the raw HTTP body: the client drops the fields of a
Crossref record it does not use (abstracts, reference lists; `verification.RECORD_FIELDS`)
and of a Europe PMC result (`auto_review.EPMC_FIELDS`) before it caches a response. PubMed
and arXiv bodies are the XML as sent.

Three alterations, and no other:

- the contact address is removed from each saved URL (`mailto=` at Crossref, `email=` at
  PubMed);
- in the cache key of a PubMed request the address is replaced by the word `CONTACT` (the
  test puts its own client's address there);
- an e-mail address inside a body is replaced by `[address removed]`, as in `records.json`
  (nine strings in three bodies: the PubMed record 17685726 and the Europe PMC results for
  10.1038/s41586-020-2649-2 and 10.1523/jneurosci.0360-19.2019).

The tests replay them by filling a real response cache and running the real client over it
with a transport that refuses every request (`extra_sources.make_client(..., offline=True)`).

| # | Request (address removed) | Retrieved (UTC) | Work | Why |
|-|-|-|-|-|
| 1 | `api.crossref.org/works/10.1002%2Ftea.3660271011` | 19:21:53 | `Zoll90` | a DOI alone |
| 2 | `www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:"10.1002/tea.3660271011"` | 19:21:55 | `Zoll90` | PubMed has no record of it (no result) |
| 3 | `api.crossref.org/works?query.bibliographic=students' misunderstandings … Zoller 1990&rows=5` | 19:21:56 | `Zoll90` | a title, an author and a year: one match |
| 4 | `eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi` (title words and `zoller[au]`) | 19:21:57 | `Zoll90` | the PubMed side of the same search (no result) |
| 5 | `api.crossref.org/works/10.1002%2Ftea.3660271011x` | 19:21:59 | none | a DOI Crossref does not have (HTTP 404): the DOI of `Zoll90` with a letter added |
| 6 | `eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?id=13896567` | 19:22:28 | `Game62` | a PMID |
| 7 | `api.crossref.org/works/10.1037%2Fh0041332` | 19:22:29 | `Game62` | the DOI PubMed gives for that PMID |
| 8 | `www.ebi.ac.uk/…/search?query=DOI:"10.1037/h0041332"` | 19:22:31 | `Game62` | the PubMed record for the DOI |
| 9 | `api.crossref.org/works?query.bibliographic=strength training and aerobic exercise: comparison and contrast Knuttgen&rows=5` | 19:22:45 | `Knut07` | a title and an author: two matching records |
| 10 | `eutils.ncbi.nlm.nih.gov/…/esearch.fcgi` (title words and `knuttgen[au]`) | 19:22:47 | `Knut07` | the PubMed side of the same search |
| 11 | `eutils.ncbi.nlm.nih.gov/…/efetch.fcgi?id=17685726` | 19:22:48 | `Knut07` | the record that search found |
| 12 | `api.crossref.org/works?query.bibliographic=backward learning in paired associates B B Murdock 1956&rows=5` | 19:22:49 | `Murd56` | a title that is only similar to the printed one |
| 13 | `eutils.ncbi.nlm.nih.gov/…/esearch.fcgi` (title words and `murdock[au]`) | 19:22:50 | `Murd56` | the PubMed side of the same search |
| 14 | `eutils.ncbi.nlm.nih.gov/…/efetch.fcgi?id=13306866` | 19:22:51 | `Murd56` | the record that search found |
| 15 | `api.crossref.org/works?query.bibliographic=acquisition, storage, and retrieval in digital and biological brains J R Manning 2011&rows=5` | 19:23:30 | `Mann11` (a thesis) | a title no source has |
| 16 | `eutils.ncbi.nlm.nih.gov/…/esearch.fcgi` (title words and `manning[au]`) | 19:23:32 | `Mann11` | the PubMed side of the same search (no result) |
| 17 | `api.crossref.org/works/10.1101%2F2020.01.27.922062` | 19:23:33 | the preprint of `ChenEtal21` | a preprint whose record names no published version |
| 18 | `export.arxiv.org/api/query?id_list=2006.10256` | 19:23:34 | the preprint of `HarrEtal20` | an arXiv preprint that names its published version |
| 19 | `api.crossref.org/works/10.1038%2Fs41586-020-2649-2` | 19:23:37 | `HarrEtal20` | that published version |
| 20 | `www.ebi.ac.uk/…/search?query=DOI:"10.1038/s41586-020-2649-2"` | 19:23:40 | `HarrEtal20` | its PubMed record |
| 21 | `api.crossref.org/works/10.1101%2F511782` | 19:24:06 | the preprint of `SilvEtal19` | a preprint DOI whose record names the published article |
| 22 | `api.crossref.org/works/10.1523%2Fjneurosci.0360-19.2019` | 19:24:07 | `SilvEtal19` | that article |
| 23 | `www.ebi.ac.uk/…/search?query=DOI:"10.1523/jneurosci.0360-19.2019"` | 19:24:08 | `SilvEtal19` | its PubMed record |
| 24 | `api.crossref.org/works/10.1167%2F15.12.782` | 20:40:01 | `MartJohn15` | an abstract of the Vision Sciences Society meeting, deposited as a journal article (the abstract rule does not see it) |
| 25 | `www.ebi.ac.uk/…/search?query=DOI:"10.1167/15.12.782"` | 20:40:03 | `MartJohn15` | its PubMed lookup (no result) |
| 26 | `eutils.ncbi.nlm.nih.gov/…/efetch.fcgi?id=12049324` | 20:40:04 | `BerrEtal02` | a PMID whose PubMed record has no DOI |
| 27 | `api.crossref.org/works?query.bibliographic=reversible septal inactivation … Y Asaka 2002 Behavioral Neuroscience&rows=5` | 20:40:06 | `BerrEtal02` | the verifier's search for the entry built from PubMed |
| 28 | `www.ebi.ac.uk/…/search?query=DOI:"10.1037//0735-7044.116.3.434"` | 20:40:07 | `BerrEtal02` | the verifier's PubMed lookup for a DOI that search found |
| 29 | `www.ebi.ac.uk/…/search?query=DOI:"10.1037/0735-7044.116.3.434"` | 20:40:08 | `BerrEtal02` | the same, for the other form of that DOI |
| 30 | `api.crossref.org/works?query.bibliographic=students' misunderstandings … Zoller 1991&rows=5` | 20:40:10 | `Zoll90` | the year one off |
| 31 | `api.crossref.org/works/10.1249%2F00005768-198704001-00264` | 20:40:37 | none (an abstract of the 1987 ACSM meeting, in a supplement issue) | a conference abstract given by DOI |
| 32 | `www.ebi.ac.uk/…/search?query=DOI:"10.1249/00005768-198704001-00264"` | 20:40:39 | the same abstract | its PubMed lookup (no result) |
| 33 | `api.crossref.org/works?query.bibliographic=strength training in older men Frontera 1987&rows=5` | 20:40:41 | the same abstract | a conference abstract found by title |
| 34 | `eutils.ncbi.nlm.nih.gov/…/esearch.fcgi` (title words and `frontera[au]`) | 20:40:42 | the same abstract | the PubMed side of that search |
| 35 | `eutils.ncbi.nlm.nih.gov/…/efetch.fcgi?id=2312474` | 20:40:43 | a later article by the same authors | the record that search found (not a match) |
| 36 | `www.ebi.ac.uk/…/search?query=DOI:"10.1101/511782"` | 20:42:33 | the preprint of `SilvEtal19` | the verifier's PubMed lookup when a typed entry keeps the preprint's DOI |

One test pairs two of these on purpose: it answers the DOI that PubMed gives for PMID
13896567 (10.1037/h0041332, row 7) with the response saved for another work (row 1), to
stand for a DOI that PubMed links to the wrong record. Both responses are real; the pairing
is the test's construction and is made in the test's own cache, not in this file.

Two tests take the DOI out of a saved PubMed record (rows 11 and 35) to stand for a paper
PubMed gives no DOI for, so that the journal name PubMed's catalogue has is what gets built.
The records are real; the removal is the tests' construction, made in the test's own cache.

The full URL of each request is in the item's `response.url`. The works named are entries of
the frozen library fixture (`tests/fixtures/cdl-prewave1-2026-09-26.bib`), which gives the
tests their expected entries.

The arXiv-only preprints of those tests need no response from here: they use the arXiv,
arXiv-page and DataCite documents of `tests/fixtures/arxiv_preprints.json`.

## `more_records.json`

Records added after `records.json` was first written, in the same form and copied the same
way by `extract_records.py`. They are kept apart so that tests which count the items of
`records.json` are not disturbed.

| Item | DOI | Copied from | Crossref retrieved | Europe PMC | What it exercises |
|-|-|-|-|-|-|
| `MeyeEtal88` | 10.1037/0033-295x.95.2.183 | apply-2026-09-25-cases.json.gz, case `MeyeEtal88` | 2026-09-25 | PMID 3375399 | a capital after a colon at Crossref, lower case at PubMed; the last author spelled differently by the two sources |

## `type_responses.json`

The lookups of `tests/test_complete_types.py` (papers in proceedings, chapters, and the
types that are not built): 24 responses, each requested once on 2026-10-05 through
`cdlbib.verification.PoliteClient`, in the form of `responses.json` (the `request` is the
client's cache key, the `response` is what the client cached). `record_type_responses.py`
beside this file is the script that made it: it runs `cdlbib.complete.propose` on the
queries below and writes out every response the client used. One alteration: the contact
address is removed from each saved URL. No body holds an e-mail address.

Keys are entries of `tests/fixtures/cdl-prewave1-2026-09-26.bib`.

| Request (address removed) | Work | Crossref type | Why |
|-|-|-|-|
| `api.crossref.org/works/10.1093%2Foxfordhb%2F9780190917982.013.2` | `KahaEtal24` | book-chapter | a chapter of an edited book; "Two Volume Pack" after the book's title |
| `api.crossref.org/works/10.1093%2Foxfordhb%2F9780190917982.013.38` | `Mann24` | book-chapter | another chapter of the same book (a DOI for a different work) |
| `api.crossref.org/works/10.1515%2F9781400882618-002` | `Klee56` | book-chapter | a series number after the book's title |
| `api.crossref.org/works/10.1016%2Fb978-0-12-108550-6.50010-0` | `BobrNorm75` | book-chapter | a chapter the citation check accepts from Crossref |
| `api.crossref.org/works/10.1007%2F978-0-387-21579-2_9` | `Scha03` | book-chapter | two container titles (a series and a book); publisher "Springer New York" |
| `api.crossref.org/works/10.1007%2F978-1-4684-1083-9_9` | `AherBeat81` | book-chapter | registry publisher "Springer US"; the imprint is Plenum Press |
| `api.crossref.org/works/10.1109%2Fcvpr.2017.354` | `BauEtal17` | proceedings-article | year and acronym in the proceedings' name |
| `api.crossref.org/works/10.1109%2Fcvpr.2010.5539970` | `XiaoEtal10` | proceedings-article | an acronym in the title |
| `api.crossref.org/works/10.1145%2F3210240.3210322` | `NguyEtal18` | proceedings-article | title and subtitle apart; an ordinal in the name |
| `api.crossref.org/works/10.18653%2Fv1%2Fd19-1410` | `ReimGure19` | proceedings-article | an ACL Anthology paper whose Crossref pages differ from the Anthology's |
| `api.crossref.org/works/10.32470%2Fccn.2018.1267-0` | `HeusMann18` | proceedings-article | no pages |
| `api.crossref.org/works/10.1109%2Ficassp.1990.115702` | `Kais90` | proceedings-article | no publication date |
| `api.crossref.org/works/10.1201%2Fb16018` | `GelmEtal13` | book | a book cited by edition |
| `api.crossref.org/works/10.1017%2Fcbo9780511802843` | `DaviHink97` | monograph | a type that is not built |
| `api.crossref.org/works/10.4135%2F9781452257044.n183` | `KahaMill13` | reference-entry | a type that is not built |
| `api.crossref.org/works/10.1136%2Febm-2023-pod.3` | not in the library | proceedings-article | a meeting abstract ("Preventing overdiagnosis meeting abstracts") |
| `api.crossref.org/works/10.1167%2F15.11.1` | not in the library | journal-article | an article of Journal of Vision 15 (2015), beside the meeting abstract 10.1167/15.12.782 of `responses.json` |
| `api.crossref.org/works?query.bibliographic=network dissection: … D Bau 2017 {IEEE} Conference on Computer Vision and Pattern Recognition&rows=5` | `BauEtal17` | | a typed paper without its DOI, found by title |
| `www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:"…"` (6 requests) | `Scha03`, `Kais90`, `KahaEtal24`, `BauEtal17`, and the two works not in the library | | the PubMed side: of the article 10.1167/15.11.1 (one result), of the meeting abstract, and of each DOI whose entry the citation check did not accept at first (no result) |

## title_only.json

Two Crossref responses fetched once on 2026-10-05 for `tests/test_core_lookups.py`, stored
as the client cached them (the request is the cache key; neither holds a contact address):
the bibliographic search for the bare title "Highly accurate protein structure prediction
with AlphaFold" (its five results are recommendations of the paper, not the paper), and the
title search among chapters, journal articles and proceedings papers that follows it (its
first result is the paper, `10.1038/s41586-021-03819-2`).

## `rule_responses.json`

The lookups of `tests/test_complete_rules.py` (a chapter's editors, ordinals in the name of
proceedings, the pages of an ACL Anthology paper): 8 responses, each requested once on
2026-10-06 through `cdlbib.verification.PoliteClient`, in the form of `responses.json`.
`record_rule_responses.py` beside this file is the script that made it: it fills an empty
cache with `responses.json`, `type_responses.json` and what an earlier run of the script
saved, runs `cdlbib.complete.propose` on the queries below, and writes out every response
the client fetched. The `request` of an API response is the client's cache key (a list); the
`request` of a document is the Anthology check's cache key, a string
(`acl-source-v1:<url>`), and its `response` is the document as that check caches it (`url`,
`body`, `document_sha256`, `retrieved_at`). One alteration: the contact address is removed
from each saved URL. No body holds an e-mail address.

| Request (address removed) | Work | Why |
|-|-|-|
| `api.crossref.org/works/10.1515%2F9783110858778-003` | M. Minsky, "A Framework For Representing Knowledge", in Frame Conceptions and Text Understanding (1979); not the library's `Mins75`, which cites another book | a chapter whose own record names the book's editor |
| `api.crossref.org/works/10.1093%2Fmed%2F9780197549469.003.0016` | a chapter of Jasper's Basic Mechanisms of the Epilepsies (2024); not in the library | a chapter record with four editors, one with a particle |
| `api.crossref.org/works/10.1117%2F12.2309486` | a paper of the Tenth International Conference on Machine Vision (SPIE, 2018); not in the library | a proceedings record that names the volume's editors; an ordinal word in the name |
| `api.crossref.org/works/10.18653%2Fv1%2Fd19-6607` | `ClanEtal19` | an ordinal word in the name of proceedings ("the Second Workshop") |
| `aclanthology.org/D19-1410.bib` | `ReimGure19` | the Anthology's record, whose pages (3982--3992) differ from Crossref's (3980-3990) |
| `aclanthology.org/D19-6607.bib` | `ClanEtal19` | the Anthology's record of the same paper |
| `www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:"…"` (2 requests) | `ReimGure19` and the Minsky chapter | the PubMed side of each entry the Crossref comparison did not accept at first (no result) |

The Crossref record of `ReimGure19` (10.18653/v1/d19-1410) is in `type_responses.json`.
