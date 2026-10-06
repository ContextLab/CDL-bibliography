# Saved responses for the intake tests

Real responses, each requested once on 2026-10-05 through `cdlbib.verification.PoliteClient`
by `record.py` (in this folder), and stored as the client cached them, in the form of
`tests/fixtures/completion/responses.json`: each item has the `request` (the client's cache
key: the URL, the parameters and whether the body is XML; for an arXiv, arXiv-page or
DataCite document, the arXiv check's key) and the `response`.

The tests replay them by filling a real response cache and running the real client over it
with a transport that refuses every request (`tests/intake_support.py`).

| File | Recorded by | Holds |
|-|-|-|
| `searches.json.gz` | `record.py searches` | 18 responses: the Crossref, PubMed (ESearch, EFetch) and arXiv API answers to the five searches in `SEARCHES`, five records per source |
| `pdf_lookups.json.gz` | `record.py pdfs` | 14 responses: the lookups `intake.propose_from_pdf` makes for the six PDFs of `tests/intake_pdfs.py` (Crossref, Europe PMC, PubMed, and the arXiv, arXiv-page and DataCite documents of arXiv:1706.03762) |
| `web_searches.json.gz` | `record.py web` | 3 responses, fetched once on 2026-10-05: the Crossref, PubMed (ESearch) and arXiv API answers to the one search of `WEB_SEARCHES`, asked as `api.find_candidates` asks it (ten records per source); replayed by the web interface's tests (`tests/web_support.py`) |
| `tui_search.json.gz` | `record.py tui` | 6 responses: the Crossref, PubMed and arXiv answers to the title search the terminal interface's Add view makes through `cdlbib.api` (ten records per source), and the lookup of its first lead (`tests/test_tui_add.py`) |
| `books.json.gz` | `record.py books` | 31 responses, fetched once on 2026-10-06: the Library of Congress SRU answers (by ISBN, by LCCN, by title and first author) and the Crossref and Europe PMC answers of the first check for the thirteen queries of `BOOKS`, and what the gate asks for the two books of `BOOKS_WRITTEN`; replayed by `tests/test_complete_books.py` and the two Add-view tests of a book |
| `typed_books.json.gz` | `record.py typed` | 10 responses, fetched once on 2026-10-06: the lookups for a typed `@book` whose year is not its record's (`TYPED_BOOK`), and the Crossref, PubMed, arXiv and Library of Congress answers to the search of `FALLBACK_SEARCH` (five records per source), for which only the catalogue has a lead; replayed by `tests/test_complete_books.py` |
| `chapters.json.gz` | `record.py chapters` | 8 responses, fetched once on 2026-10-06: the Crossref records of the four chapters of `CHAPTERS` (two container titles each), the Crossref book-type records found by their ISBNs, and the first check's lookups; replayed by `tests/test_complete_booktitle.py` |
| `booktitle_model.json` | `record.py booktitle` | one real answer of the Dartmouth Chat adapter's `extract` phase (model `zai-org.glm-5.3`), recorded on 2026-10-06, to the lines of the page of 10.1007/978-3-031-20910-9_48 at its publisher that mention either container title; replayed by `tests/test_complete_booktitle.py`. It holds only what the replay needs: the 30 lines the model was given (the lines that mention either title, each with two lines of context; the reading names their SHA-256, so none of them can be cut), the page's address, hash and retrieval time, the reading's `booktitle` with its passages, and the chapter record's DOI, type, titles and ISBNs |
| `model_extract.json` | `record.py model` | one real answer of the Dartmouth Chat adapter's `extract` phase (model `zai-org.glm-5.3`), recorded on 2026-10-05, for the first two pages of the `unknown` PDF of `tests/intake_pdfs.py`, saved with the pages it was given; replayed by `tests/test_intake_model.py::test_recorded_model_reading` |

Alterations, and no other:

- the contact address is removed from each saved URL (`mailto=` at Crossref, `email=` at
  PubMed);
- in the cache key of a PubMed request the address is replaced by the word `CONTACT` (the
  test puts its own client's address there);
- an e-mail address inside a body is replaced by `[address removed]`, except in the arXiv,
  arXiv-page and DataCite documents, which are kept byte for byte because the arXiv check
  verifies their SHA-256.

Left out of `booktitle_model.json`, and nothing else: every other line of the page (490 of
its 520: navigation, the chapter's text and reference list, consent and account text); any
query string or fragment of the page's address (it had none); the fields of the reading
other than `booktitle` (title, authors, year, publisher, DOI, entry type) and its list of
uncertainties; the provider's response id and token counts (the provider and model names
are kept); every field of the Crossref record other than the five named above (the authors
among them). E-mail addresses were removed from the page's lines before the model was given
them, and the recorder refuses to save a file that holds one.

The bodies are what the client keeps: it drops the fields of a Crossref record it does not
use (`verification.RECORD_FIELDS`) and of a Europe PMC result (`auto_review.EPMC_FIELDS`).
PubMed and arXiv bodies are the XML as sent.
