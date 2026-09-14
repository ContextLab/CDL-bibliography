# Proceedings record for `VaswEtal17`, September 14, 2026

Handoff item 2 asked for the actual proceedings record behind `VaswEtal17`, to
establish the series title, volume and pagination that the PDF front page does
not carry. This resolves it. No bibliography entry was edited and no approval was
recorded.

## Method and its limits

Requests here did **not** carry a `mailto`, so they did not use the Crossref
polite pool. That was an explicit instruction for a bounded one-off lookup.
`PoliteClient` still refuses to run without a real contact
(`bibcheck/verification.py:325`), and bulk verification traffic is unaffected.
Reproduce with:

```bash
python verification/neurips_record_lookup.py 3f5ee243547dee91fbd053c1c4a845aa
```

## Crossref does not hold this record

Two Crossref queries returned nothing relevant. A bibliographic title search
returned five unrelated works, the closest being a 2025 Springer chapter titled
"Is Attention All You Need?". A container search for the series, filtered to
2017–2018, returned only papers from "LatinX in AI at Neural Information
Processing Systems Conference 2018", a separate venue.

NeurIPS proceedings papers before 2019 have no registered DOIs, so Crossref
cannot establish this citation at all. The benchmark's abstention control for
`VaswEtal17` is correct for a reason stronger than previously recorded: it is not
that later posted-content copies fail to establish the proceedings record, but
that the proceedings record is absent from the provider entirely.

## The publisher record

The NeurIPS proceedings site supplies both a BibTeX record and a metadata
document for the paper hash above. Together they establish every field the front
page left open.

| Field | `cdl.bib` | Publisher record | Source |
| --- | --- | --- | --- |
| Booktitle | Advances in Neural Information Processing Systems | identical | `booktitle`, and `"book"` in the metadata |
| Volume | 30 | 30 | `volume = {30}` |
| Pages | 5998--6008 | 5998, 6008 | `"page_first"`, `"page_last"` |
| Year | 2017 | 2017 | `year = {2017}` |
| Authors | eight, ordered | same eight, same order | `author` |

The publisher's own BibTeX leaves `pages` empty; the pagination comes from the
metadata document, which is the same record's companion. The record also names
Curran Associates, Inc. as publisher and lists seven editors, neither of which
the citation carries. Both are optional for this entry type.

## Two differences that are not factual errors

- **Title case.** `cdl.bib` reads "Attention is all you need"; the publisher
  record reads "Attention is All you Need"; the PDF heading reads "Attention Is
  All You Need". Three different casings of the same title. The repository
  applies its own sentence-case convention through `helpers.format_title`, so
  this is a house-style question, not a discrepancy to correct here.
- **Entry type.** The citation uses `@conference`; the publisher record uses
  `@inproceedings`. The automatic comparator supports `inproceedings` and not
  `conference`, which is why this entry cannot clear automatically even now that
  its fields are confirmed.

## Status

The entry's factual claims are supported by the publisher's record. This is
documentary evidence from a single provider, not a human review, and no status
was changed: `VaswEtal17` remains `needs_review`, and the benchmark fixture that
expects it to abstain is unchanged and still passing.
