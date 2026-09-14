# Cached source-text audit, September 11, 2026

This follow-up inspects the cached first-page PDF text separately from Qwen's
returned fields. It is an assistant audit, not independent human review or a
visual inspection of the rendered PDF. No new network/model calls or citation
approvals were made. The initial citation was compared only after inspecting
the source text.

| Entry | Evidence in the document's own front matter | Remaining boundary |
| --- | --- | --- |
| `McInEtal18b` | Heading contains the complete UMAP title/subtitle. Byline has four ordered authors, including Großberger with an attached numerical affiliation marker. Explicit publication date establishes 2018; the page footer supplies Journal of Open Source Software, volume 3, issue 29, article number 861, and DOI 10.21105/joss.00861. | These fields support the existing citation. The PDF also cites other UMAP works in its prose; those references must not supply this article's metadata. The generic `article` category is an interpretation, not a literal PDF field. No new approval recorded. |
| `VaswEtal17` | Heading and byline establish the title and eight ordered authors. The conference footer establishes the conference name and 2017. | This page does not establish the cited series title, volume 30, or pages 5998–6008. The citation uses `conference`, which the automatic comparator does not support. An identified proceedings landing page/volume record is needed; the printed conference name must not be silently equated with the series title. |

Qwen's current passage selections agree with these observations, including its
printed conference-name value rather than an inferred series name. This checks
two examples and cannot measure broader extraction accuracy. Initials in a
citation are not proof of personal identity; accents and the Ł in the proceedings
author byline should remain available in the evidence.

Local evidence:

- `.bibcheck/debug/dartmouth-cd990sas/pages.json` and `result.json`: complete
  known JOSS landing-page → PDF → Qwen run.
- `.bibcheck/debug/dartmouth-qypkrf5r/pages.json` and `materialized.json`:
  proceedings extraction, materialized by replay after the author-parser fix.

Cached text can contain extraction errors. Before broadening PDF acceptance,
compare more independently selected publications with their rendered PDFs and
publisher/repository records, and add negative cases where the selected text
is from a reference, affiliation, receipt/copyright date, or another version.
