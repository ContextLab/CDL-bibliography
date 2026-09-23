# PDF-evidence verifier and hard benchmark (2026-09-22)

`bibcheck/pdf_evidence.py` decides, field by field, whether a local PDF of the
cited version supports a `cdl.bib` entry. The decision is deterministic code over
`pdftotext -bbox-layout` text with word positions. No model is called. A model
could later suggest candidate lines, but nothing it says would be read by this
code.

Nothing here writes approvals, edits `cdl.bib`, or touches
`.bibcheck/verification.sqlite3`. **The verifier is not wired into any approval
path.** Enabling it is the user's decision (see "Open risks").

## How a field is decided

Each field comes out `supported`, `contradicted` or `absent`. The result records
the exact source line, its page and its role. An entry passes only if all of these
hold:

- it is an `@article`;
- title and byline are anchored together;
- the PDF has no version stamp;
- every cited title/author/journal/year/volume/number/pages/doi field is
  `supported`;
- no other bibliographic field is left unchecked (`publisher` on `@article` is
  ignored under the 2026-09-22 drop policy).

| Field | Only accepted from | Never accepted from |
|-|-|-|
| identity | a heading run whose text equals the cited title exactly (letters, digits and hyphens), with no same-size line continuing it (checked by position, across text blocks), sitting directly above a byline that matches the authors | running heads, reference lists, cover pages, other articles' headings |
| author | the byline under that title: every printed person, in order. Surnames must match exactly, including diacritics. Initials must correspond one-to-one, and a missing middle initial or an extra, dropped or swapped author is `contradicted`. If the entry is fuller than the print (e.g. "John" against "J."), the result is `absent`. Accents extracted as spacing marks are re-attached. A name-like row further down (for example after an affiliation row the code does not recognise) gives `absent` | acknowledgments, references, correspondence lines |
| journal | a bounded full name in a header/footer band, a repeated running head, or the masthead above the title; the one listed acronym (PNAS); a word-prefix abbreviation that no other `cdl.bib` journal also fits | a name inside a longer name (`Cognitive Neuroscience` inside `Journal of Cognitive Neuroscience`), a name followed by `:` and a section title, letter-spaced squashing except on genuinely letter-spaced text |
| volume / number / year | publisher citation-line templates (Elsevier, APA, MIT, OUP, JNeurosci, Cell, Nature, PNAS, Springer, PLOS, Frontiers, APS, Psychonomic), labelled `Vol./No./Issue`, issue dates, and `Citation:` self-citation lines, on the first page's bands or repeated running heads. All such records must agree | body text, statistics, figure/experiment numbers, DOIs/ISSNs/PII/price codes, received/revised/accepted/online/download dates, copyright years, lines that look like references |
| pages | a printed first–last range, or page numbers printed on the identity page and on the final PDF page of an unbroken sequence. First pages are never inferred from later pages. An end page is not taken when another article may start on a following page (a run-on start low on the last page is allowed). An article number (e-number, `(2018) 9:2715`, Elsevier 6-digit) must match exactly, and a 1–N range is contradicted | numbers elsewhere on the page, reference ranges |
| doi | a `doi` line in the first page's bands or front matter | references |
| version | fails on arXiv/bioRxiv/PsyArXiv stamps, author or accepted manuscripts, NIH/Europe PMC, "Article in press", online-first/Early Edition, placeholder pagination (`VOL 000`), reprints | stamps are read only from bands, margins and the front matter |

Cover pages (JSTOR, ResearchGate, HighWire, Science) are recognised and skipped.

## Benchmark

`build.py` writes `cases.json`: 87 real entries, each with its local PDF recorded
by SHA-256. Only short bibliographic lines are stored as evidence, and the builder
refuses to run if any quoted line is missing from the extracted text.

| Base label | Entries | How labelled |
|-|-|-|
| accept (published version prints every cited field) | 57 | by inspecting the extracted bands, title block and byline. 43 were used during development; 10 are a random held-out draw (seed 20260922), labelled before the verifier ever ran on them; 4 were found by the coverage run and then checked by hand |
| abstain (entry correct, PDF does not print a cited field) | 12 | e.g. Nature/Nat Commun/Cell print no issue; year only as a copyright year; issue only inside a price code `89(5)/052102(8)`; News & Views with no volume or pages |
| wrong_version | 11 | NIH or accepted manuscripts, arXiv, article-in-press, APA online-first, PNAS Early Edition, OUP advance access, a retyped reprint |
| wrong_work | 4 | the local file is a different article by the same first author; one first page opens with the tail of another article |
| entry_error | 3 | real `cdl.bib` errors: 4 of 6 authors; "Inter-response" where the PDF prints "Interresponse"; `JEP: General` cited for a 1968 PDF of the parent journal |

On each accept base, 34 generators plant **one** wrong value, taken where possible
from the same PDF. They cover:

- **volume and issue:** a number from the body (a statistic or figure number), from
  DOI/ISSN/price-code digits, or equal to the first page; volume and issue swapped;
  a double issue; a supplement;
- **pages:** the page number printed on page 2 used as the first page; the end page
  ±1; a range from the reference list; a first page taken from the body; a 1–N range
  in place of an article number; an article number off by one;
- **year:** a received or copyright year (for example © 2012 on a 2013 issue); a
  year cited in the body;
- **authors:** swapped, dropped or extra authors; a last author replaced by a person
  from the reference list; a missing middle initial; a changed initial; a misspelled
  given name; a dropped accent;
- **title:** the article's own running head; a missing subtitle or last word; one
  extra word; a dropped hyphen; the title of a neighbouring article or reference;
- **journal:** a similar name (`Neuropsychologia`→`Neuropsychology`,
  `J Neurosci`→`J Neurophysiol`, `Cognitive Brain Research`→`Brain Research`, …);
  the parent title without its section;
- **doi:** one digit changed.

That makes 1,162 cases in total: 57 expected accepts and 1,105 expected rejects.

```bash
python verification/pdf-benchmark/build.py            # rebuild cases.json (needs the local library)
python verification/pdf-benchmark/run.py              # benchmark, about 15 s
python verification/pdf-benchmark/run.py --coverage --stress
```

### Results (2026-09-23)

| Measure | Value |
|-|-|
| false accepts | **0** / 1,105 expected rejects |
| field false supports (the planted field reported `supported`, even when another field blocked the entry) | **0** |
| true accepts | 55 / 57 |
| missed matches | 2 (3.5%): FolkEtal18 (an ORCID icon extracted as "X" inside the byline) and BurgEtal02 (a byline split across columns next to body text; the code abstains) |
| held-out first contact | 6 / 9 accepted. The one apparent false accept (ShinEtal08) was **my labelling error**: I had labelled it from the footer only, and the `Citation:` line does print volume 3, so the label was corrected. After the held-out misses were fixed (a `Volume 2, Number 2, 2012` year form and Elsevier's `Ž 2000 .` glyphs), 8 / 10 |

These numbers are not an unbiased accuracy estimate: 43 of the accept bases were
used while building the rules. Every new class of adversarial case found real
defects on first contact, and each was fixed and kept as a regression:

- a page number read as a year (`1664 VOLUME 18`);
- a section-title journal (`Journal of Experimental Psychology:` / next line);
- a mis-encoded running head (`CognitiÕe Brain Research`) matching `Brain Research`;
- a title whose last word sits in its own text block;
- a byline continuing below an affiliation row with no affiliation keyword;
- hyphen-insensitive title matching.

The last two were found as **real false accepts** in the coverage run
(RakiEtal98, KahaJaco00).

**Stress run** (`--stress`, not labelled): the 34 generators were run on all 405
key-named article PDFs, giving 7,322 planted variants. Five were reported
`supported`, and all five were reviewed by hand. In each, the planted value is what
the PDF actually prints:

- the PDF is another version or another work (MaguEtal99, SahaSmit14);
- the entry itself is wrong (KahaJaco00, Murd68);
- MullWehn88: the 1988 all-caps byline prints `MULLER`, so an entry without the
  umlaut is "supported" by the print. This is a policy question (see "Open risks").

## Coverage of the 2,753 needs_review entries (offline dry run, `coverage.json`)

- 232 have at least one local PDF: a file named by cite key, or a title/DOI hit in
  `.bibcheck/local-library/candidates.json`. The other 2,521 have none.
- The verifier would accept **4** (Free77, MankEtal12, Mill10, RichEtal99), all
  checked by hand. Mill10's file is misnamed `Mill12.pdf`; its content is the cited
  2010 article.
- Among the 155 unaccepted articles, the most common blockers are: the PDF is not the
  cited version (18 have version stamps); the title is not printed or not anchored
  (171 of the 232 not supported, all entry types); the year is printed only as a copyright or
  online year; Nature/Cell-family PDFs print no issue; and the fields of non-article
  types (booktitle/editor/address) cannot be checked.

Local PDFs therefore resolve very few of the unresolved entries. Their better use is
as evidence on the human review page, and for flagging entry errors the PDF
contradicts (such as RakiEtal98 and Murd68).

## Open risks

- The rules come from a few hundred PDFs from mainstream publishers. Unseen layouts
  (two-column title pages, author blocks, OCR'd scans) mostly cause abstention, but
  both real false accepts found so far came from unseen layouts. Before any
  enablement, run a fresh held-out sample with planted variants on the new layouts.
- All-caps or OCR bylines can drop diacritics (MullWehn88). A "printed byline wins"
  policy would then approve an unaccented name. Decide whether all-caps bylines may
  confirm the absence of accents.
- Copyright-only years (JOCN, APS, Nature Human Behaviour) and unprinted issues always
  abstain, by design.
- Scanned PDFs without a text layer (30 in the library) are not handled. The existing
  OCR text has no positions, so it is never used.
- `cases.json` stores entry fields as of 2026-09-22. If `cdl.bib` changes, the cases
  still test the verifier, but they no longer describe the current entries.
