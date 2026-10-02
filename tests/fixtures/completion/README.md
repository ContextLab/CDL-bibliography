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
