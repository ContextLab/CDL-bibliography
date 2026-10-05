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
| `tui_search.json.gz` | `record.py tui` | 6 responses: the Crossref, PubMed and arXiv answers to the title search the terminal interface's Add view makes through `cdlbib.api` (ten records per source), and the lookup of its first lead (`tests/test_tui_add.py`) |
| `model_extract.json` | `record.py model` | not present: one real answer of the Dartmouth Chat adapter's `extract` phase. It needs a Dartmouth Chat API key; none was available on 2026-10-05, so none was recorded and `tests/test_intake_model.py::test_recorded_model_reading` is skipped until it is |

Alterations, and no other:

- the contact address is removed from each saved URL (`mailto=` at Crossref, `email=` at
  PubMed);
- in the cache key of a PubMed request the address is replaced by the word `CONTACT` (the
  test puts its own client's address there);
- an e-mail address inside a body is replaced by `[address removed]`, except in the arXiv,
  arXiv-page and DataCite documents, which are kept byte for byte because the arXiv check
  verifies their SHA-256.

The bodies are what the client keeps: it drops the fields of a Crossref record it does not
use (`verification.RECORD_FIELDS`) and of a Europe PMC result (`auto_review.EPMC_FIELDS`).
PubMed and arXiv bodies are the XML as sent.
