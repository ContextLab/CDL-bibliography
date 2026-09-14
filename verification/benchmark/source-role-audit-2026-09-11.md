# Source-role audit, September 11, 2026

Literal grounding proves that a value was copied from the byte offsets it cites.
It does not establish that the copied text states the work's own metadata. This
note records what that gap admits, and what now flags it. No network or model
calls were made, no citation was approved, and `cdl.bib` was not edited.

## What literal grounding admits

Each row is a wrong answer. Before this change every one reported
`grounding: literal_text_present` with `unsupported_fields: []`.

| Selected line | Claimed as | Why it is wrong |
| --- | --- | --- |
| `Received: 3 January 2016 / Accepted: 9 May 2018` | `year = 2016` | A receipt date is not a publication date. |
| `© Springer 2019` | `year = 2019` | A copyright year can differ from the publication year. |
| `arXiv:1706.03762v5 [cs.CL] 6 Dec 2017` | `year = 2017` | A preprint stamp dates a version, not the cited record. |
| `[1] B. Other. Attention Is All You Need. NeurIPS, 2017.` | `title = Attention Is All You Need` | A reference-list entry describes another work. |
| `1 Dartmouth College, Hanover NH` | `publisher = Dartmouth College` | An affiliation is not a publisher. |
| `Alice Smith, Bob Jones, Carol White` | `author = Alice Smith and Bob Jones` | Every named author is present; the omission is invisible. |

The first three take three different years from one front page, each fully
supported. A comparator reading only `grounding` cannot rank them.

## The added signal

Each field's evidence now carries a `role_risk` list, collected in
`role_risk_fields`, and every match also becomes an explicit uncertainty:
`reference_list`, `receipt_or_revision_date`, `copyright_line`,
`preprint_version_stamp`, `affiliation_line`, `institution_named_as_venue`,
`possible_omitted_author`.

These are pattern heuristics over the selected passages. They never approve and
never block; everything remains `needs_review`. They deliberately over-flag,
because a false positive withholds acceptance while a false negative admits a
wrong value. **An empty `role_risk` is not evidence that the role is correct**;
it means no listed pattern matched, and the list covers seven roles out of an
open set.

`reference_list` is structural rather than lexical: it fires when a selected
passage falls at or after a references heading on its own page.

## Checked against the two cached runs

Replaying both saved extractions through the new code flagged nothing. Every
field of `McInEtal18b` (title, journal, volume, number, pages, year, doi,
ENTRYTYPE, author) and of `VaswEtal17` (title, booktitle, year, author) returned
an empty `role_risk`.

Two boundaries that behave correctly and are worth keeping visible:

- The JOSS fields were selected from `p1l30`, the article's own "how to cite"
  footer. That line has reference-entry shape but no references heading precedes
  it, so it is not flagged. Self-citation is a legitimate source; reference shape
  alone is not the test.
- Page 1 of the same PDF carries both `Submitted: 19 July 2018` and
  `Published: 02 September 2018`. A year taken from the first is flagged; one
  taken from the second is not, because that line does state the publication
  date.

## Limits

This checks seven named roles against two cached PDFs and a set of constructed
fixtures. It is not a measurement of extraction accuracy, a human review of any
PDF, or grounds for a PDF acceptance rule. The recommendation in the September 11
handoff stands: independently label a small set of publisher records and rendered
PDFs before considering any automatic acceptance.
