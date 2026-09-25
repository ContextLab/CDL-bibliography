# Research agent brief (scaled research route, 2026-09-25)

You research ONE batch of 20 held BibTeX entries from `verification/research-2026-09-25/queue.json`
(entries whose `batch` equals your batch number). Follow
`verification/research-pilot-2026-09-24/PROTOCOL.md` exactly (output schema, verbatim quotes that
cover the WHOLE value, acceptable sources, identity first, house format incl. initials without
periods, no suffixes, issue ranges `3--4`, proceedings names without year, @book without pages,
editions and all ordinals `N\textsuperscript{..}`, DOIs for the published version, preprints cite
the latest version and report a published version as a replacement candidate, conference abstracts
via the society planner). House conventions: check how cdl.bib already writes a value before
proposing one (`git show HEAD:cdl.bib`). Never drop an initial only because a source omits it.
User rules live in `verification/resolution-plan-2026-09-22/README.md`.

Useful routes (read-only use): Crossref API JSON, PubMed E-utilities (efetch; the PubMed web page
blocks scripts), Europe PMC, publisher pages, Library of Congress catalogue, OSF API, DataCite,
ACL Anthology, SfN planner (see `verification/research-pilot-2026-09-24/SFN-SOURCE.md`), the local
PDF library (read-only) at /Users/jmanning/Library/CloudStorage/Dropbox-DartmouthCollege/Jeremy Manning/Papers
(cite as `file:<path>#page=<n>`). Semantic Scholar/OpenAlex/Google Scholar are leads only.

Write your output file incrementally (after each entry). Put helper scripts ONLY in your own
scratch folder. Before finishing, run
`.venv/bin/python verification/research-pilot-2026-09-24/validate.py <your wave folder>` is NOT
required; instead self-check each quote by fetching. Accuracy over coverage: `ambiguous` or
`no_source` with notes beats a guess. About 5-10 tool calls per entry.
