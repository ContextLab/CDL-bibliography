# Research pilot protocol (2026-09-24)

Each researcher receives entries from `sample.json` (its batch number) and writes
`batch-<N>.json`: a JSON list with one object per entry:

```json
{
  "key": "Cite key",
  "verdict": "verified | correction | no_source | ambiguous",
  "identity": {"url": "...", "quote": "...", "why": "one sentence"},
  "fields": {
    "<field>": {"status": "confirmed | corrected | not_found",
                "value": "value in house format",
                "evidence": [{"url": "...", "quote": "..."}]}
  },
  "notes": "anything the reviewer must know (versions, reprints, conflicts)"
}
```

Rules:
- Every confirmed or corrected field needs at least one evidence item whose `quote`
  is copied **verbatim** (exact characters, a short span of 3-40 words) from the page
  or PDF at `url`. A validator fetches each URL and rejects any quote not found there.
- Acceptable sources: the publisher's article/book page, the DOI landing page, PubMed,
  Crossref/DataCite API JSON (quote the raw JSON value), JSTOR stable pages, library
  catalogue records (LoC, WorldCat, university catalogues), proceedings sites (NeurIPS,
  PMLR, ACL Anthology, CogSci/eScholarship), arXiv/bioRxiv/OSF, the author's or lab's
  own publication page only for items no other source covers, and local PDFs from
  the read-only Papers library, cited as `file:<absolute path>#page=<n>`.
  NOT acceptable as sole evidence: Google Scholar, Semantic Scholar, ResearchGate,
  Wikipedia, other papers' reference lists, citation-manager exports.
- Identity first: show the record is the same work (title + authors + year + venue).
  A reprint, a later edition, a translation, a preprint vs. its journal version, or
  a book review is a DIFFERENT work: say so and use `ambiguous` unless the cited
  version itself is found.
- House format: authors are initials without periods, one per given name, all
  initials the source gives (`M E Smith and D C Young`); surnames with accents and
  particles as printed (`{de la Rocha}`); titles in sentence case, lowercase after a
  colon, braces around proper nouns and acronyms; pages `start--end`; no `publisher`
  on @article.
- Evidence must cover the WHOLE value, not just the part that changed: every author
  surname in an author list, every word of a title, both page numbers. Use several
  quotes if needed (the validator joins them).
- House conventions (check how cdl.bib already writes a value before proposing one):
  booktitles in title case (only `title` is sentence case); double issues `3-4`, not
  `3--4`; publisher short house forms (`Erlbaum`, not "Lawrence Erlbaum Associates");
  US addresses with braced state codes (`New York, {NY}`, `Mahwah, {NJ}`); a chapter
  with a booktitle is `@incollection`, not `@inbook`.
- Never drop an initial the citation already has only because a source omits it; drop
  it only when a source prints a different initial or name.
- Issue numbers only if a source states them. Never carry a value over from the
  citation and call it confirmed.
- `no_source` only after a genuine search (say where you looked in `notes`).
