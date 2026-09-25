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

## Lessons from wave 1 (independent review: 24% random-sample error rate) — MANDATORY

1. **Every DOI you propose must resolve**: check `https://doi.org/api/handles/<doi>` returns 200
   and that the DOI's Crossref/DataCite record is this work. Never build a DOI from a
   taylorfrancis.com (or any) URL path.
2. **Keys**: if your correction changes the year, first author or author count, compute the new
   key and check it against `git show HEAD:cdl.bib`. If it exists and is the same work, say
   "duplicate of <key>"; if it is a different work, say "key collision".
3. **Patents**: the year is the grant/issue year, never the filing or priority date.
4. **Apply house rules yourself**: no name suffixes (Jr, III), hyphenated initials (J-P), initials
   without periods, US addresses `City, {ST}`, ordinals `N\textsuperscript{..}`, issue ranges
   `3--4`, booktitles without year, @book without pages, keep accents.
5. **Never propose an empty value.** A field you could not confirm is `not_found` and is left alone.
6. **Print year beats online-first year.**
7. Verdict `ambiguous`/`no_source` only after checking library catalogues (LoC, Harvard, WorldCat
   records) and the obvious alternatives; the reviewer found several resolvable ones.
