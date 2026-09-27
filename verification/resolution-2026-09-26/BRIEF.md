# Resolution brief (2026-09-26)

The user no longer checks entries one by one. Every entry in `queue.json` was left
unresolved by the research waves (held fields, needs_user flags, ambiguous or no_source).
Your job is to resolve each one under the user's standing rules
(`verification/resolution-plan-2026-09-22/README.md`, "Standing rules for the remaining waves"):

1. If the entry cannot be verified automatically, verify it by web search and cite the
   evidence: a URL and a **verbatim** quote from that page for every value you set. If no
   evidence exists for the work at all, the decision is `drop`.
2. No conference abstracts. Before dropping one as an abstract, confirm it really is an
   abstract (meeting abstract book, poster/talk abstract, supplement abstract), not a full
   paper. Full papers in conference *proceedings* are kept.
3. Every value must be **as printed** in the official record (publisher page, Crossref /
   DataCite record, PubMed, the printed PDF, library catalogue for books), up to bibcheck's
   formatting (initials without periods, sentence-case titles with braces for proper nouns,
   `--` page ranges, house journal names from bibcheck's journal table).
4. Anything you cannot settle goes in `questions`, phrased as a question about a **rule** that
   would apply to other entries too. Ask about a single entry only when no rule fits.

## Inputs for each key

- `verification/research-2026-09-25/wave<N>/merged.json`: the current entry, the post-check's
  final changes, flags (why it is held), the key plan, and the reviewer's verdicts.
- `verification/research-2026-09-25/wave<N>/batch-*.json`: the researcher's evidence.
- `verification/research-2026-09-25/wave<N>/review.json`: independent reviewer notes (not every key).
- House rules: `verification/research-2026-09-25/AGENT-BRIEF.md` and the resolution-plan README.
- Read the bibliography only via `DEVELOPER_DIR=/Library/Developer/CommandLineTools git show HEAD:cdl.bib`.

## How to decide common flags

- `field_not_found`: find the value as printed, or `withdraw` the proposed change (keep the
  current value) when the current value is itself confirmed by a source; if neither the
  current nor any value can be confirmed for a required field, say so in `notes`.
- `doi_record_conflict` / `print_year_conflict`: the printed record wins (issue cover date,
  printed page range). Quote it.
- `key_rename` / `key_collision`: keys must follow the corrected metadata (user); a freed
  suffix may be reused. Just confirm the metadata that drives the key.
- `quote_check_failed`: re-quote from a page that prints the value, or withdraw.
- `other_version_named`: cite the published version (preprints cite the latest version;
  software cites its first version, with the first version's year and no version number).
- `duplicate`: confirm both entries are the same work before merging; name the keeper.
- `no_source`: search thoroughly (publisher, Crossref, PubMed, Google Scholar via WebSearch,
  author pages/CVs, WorldCat/LoC/HathiTrust/Internet Archive). Only then `drop`.

## Output (one file per batch you own): `verification/resolution-2026-09-26/batch-NN.json`

```json
[{"key": "Xyz99",
  "decision": "apply" | "drop" | "keep",
  "set": {"field": {"value": "...", "url": "...", "quote": "verbatim text"}},
  "withdraw": ["field", ...],
  "remove": ["field", ...],
  "entrytype": "article",
  "new_key": "Xyz00",
  "merge_into": "OtherKey",
  "drop_reason": "no evidence found after: ... | confirmed conference abstract: <quote>",
  "notes": "one or two sentences: what was checked and why",
  "questions": ["rule-level question ..."]}]
```

`apply` means: apply the post-check's final changes plus your `set`/`withdraw`/`remove`.
`keep` means: leave the entry exactly as it is in HEAD (only when HEAD is confirmed correct).
Every `set` value needs a URL and verbatim quote the validator can fetch (no image-only scans).

Keep NCBI E-utilities to at most 1 request per second. Prefer direct APIs and catalogues;
WebSearch quota may be limited.

## Clarification (2026-09-26, after batch 9)
"As printed" is subject to the user's standing house-form rules, which are formatting rules:
no name suffixes (Jr, III — drop them even when printed), initials without periods, all
initials the source gives, keys follow corrected metadata. Do not restore a suffix because the
byline prints it (TrenEtal93 in batch 9 was wrong to).

## Rule answers (user, 2026-09-26) — apply these from now on
- Em dashes in titles: `a---b`, no spaces.
- Conflicting records (e.g. last page), printed PDF unseen: publisher page / Crossref wins; then PubMed.
- Author names: the author's correct, most complete name (fix misprints like 'Tulvig', 'Wickelgran', 'Waszcak'→'Waszczak' if the author's other records spell it so; keep known middle initials); cite evidence from other records of the same author.
- Unconfirmable optional fields (chapter pages, editors, volume) on a verified work: `remove` the field (do not keep an unconfirmed value, do not infer from secondary sources).

## Rule answers round 2 + defaults (2026-09-26) — see verification/resolution-plan-2026-09-22/README.md
- No verifiable record → drop, even if the user earlier marked it "real article, keep".
- Evidence accepted: image-only scans (transcribe the quote from the page image and say so in notes), pages read in a real browser when fetches are blocked, and an abstracting-index citation alone (PsycINFO/Google Scholar) is enough to keep an entry.
- End page not printed anywhere: infer from the next item's printed start page − 1 (cite the TOC/next item).
- Dissertation Abstracts International entries → @phdthesis (school, degree year) from a catalogue/DataCite record.
- Follow the "Defaults chosen by Claude" list in the README for supplements, roman volumes, subtitles, ×, ACM volumes, two-part articles, software titles, web-only articles, "and others" lists, multi-volume editors, quoted titles, compounds, renamed journals, collective abstract records, society-proceedings years, reprints, and title misprints.
