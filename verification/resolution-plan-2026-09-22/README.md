# Plan to resolve all 2,753 unresolved entries — drafted 2026-09-22

Baseline: 3,669 metadata_verified / 2,753 needs_review (commit db310f3).
Five read-only planning agents classified every unresolved entry from cached
evidence. Detailed plans (per-key tables, pilots, negative controls):

| Group | Entries | Plan |
|-|-|-|
| Articles, no unambiguous match | 1,945 | [plan-articles.md](plan-articles.md) |
| Books, chapters, theses, reports | 413 | [plan-books.md](plan-books.md) |
| Proceedings, preprints, misc | 158 | [plan-proceedings.md](plan-proceedings.md) |
| DOI coordinate / suffix conflicts | 136 | [plan-doi-conflicts.md](plan-doi-conflicts.md) |
| Correction / retraction notices | 101 | [plan-notices.md](plan-notices.md) |

Classification data is in `data/`. Estimates below are the agents' estimates
from cached evidence, not measurements.

## Decisions recorded from the user (2026-09-22)

- Retractions: flag each for the user; nothing automatic. (None found on cited works in cached evidence.)
- Content-only errata with fully matching metadata: auto-verify, notice kept in the report only (no BibTeX note).
  If the erratum text can't be retrieved, decide on a batch review page.
- Coordinate conflicts: auto-correct when publisher and PubMed agree; otherwise human.
- Preprint later published: default swap to the published version under a NEW key and remove the preprint entry,
  but ask per entry first. Removing old keys without a usage check is acceptable.
- Add verified DOIs to entries once a full match is verified.
- @misc: registry (DataCite/Zenodo/GitHub release) or live page match counts; dead links go to the user.
- Named reviewer: Jeremy Manning only.
- Unverifiable entries: local PDF evidence, then the user's sign-off (recorded as human-verified).
- `publisher` on @article: drop the field.
- Year: the print year wins (accept when print and issued both equal the cited year; correct the ~24 online-year citations).
- Entry types: convert @conference → @inproceedings and titled-chapter @inbook → @incollection in cdl.bib.
- Printed PDF of the cited version beats repository metadata on bylines.
- Corporate authors: match the printed byline exactly.
- APA `10.1037//` DOI forms may be used as lookup keys only; acceptance still needs a full match.
- Conference abstracts (32): flag for removal (list them for confirmation before deleting).
- External APIs: ProQuest via the library login only; no personal API. Skip; theses use local PDFs + sign-off.

## Path forward (phased)

Every phase keeps the existing guarantees: frozen proposals, staging diff limited
to the batch, all cite keys kept (except the approved preprint swaps and removals),
zero-request/zero-write repeat, exact fresh restore, tests + benchmark green,
local commit per batch.

**Phase 0: false flags and matcher rules (code only, no bib edits).**
Tie notice/coordinate/suffix flags to the cited work's own DOI (clears 22 notice
and 56 coordinate false flags, which fall back to their real issue); collapse
byte-identical Crossref records; print-year rule; duplicate-DOI rule (APA `//`
twins, reissued chapters, preprint twins); documented journal variants; editor /
address / organization / chapter checkers (parent-book Crossref record or LoC);
widened LoC record parser. Each rule gets real positive and negative controls.

**Phase 1: policy edits (bulk, mechanical).** Drop `publisher` from @article;
convert @conference and @inbook types; print-year corrections. Note: this changes
fingerprints of some *already verified* entries, so they re-verify (mostly from cache).

**Phase 2: source-backed correction batches.** pmccoord006 (7), artno001 (15,
new article-number rule), pmccoord007 (~15), suffix003 (~11); article single-field
corrections where Crossref and PubMed agree (pool of 513); PubMed lookups by APA
`//` DOI form and by volume/page/author; add verified DOIs.

**Phase 3: new source routes.** PMLR / NeurIPS / ACL Anthology adapters; bioRxiv
re-judge under policy 2 plus version pins; PsyArXiv via the OSF API; Zenodo/DataCite
and CITATION.cff for software; the PEP JSON; chapter two-layer rule (catalogue edition +
chapter record or inspected TOC page image); local PDF library evidence.

**Phase 4: user-approval queues.** Preprint→published swap proposals (per entry);
removal list for the 32 conference abstracts; 79 errata acknowledgements.

**Phase 5: human review page.** One review page (artifact with a shared decision
store, or static HTML + CSV import) for everything still unresolved: fields, a
per-source match grid, local PDF snippet, a suggested decision, bulk-accept per
class; decisions import through a CLI that checks fingerprints.

Rough expected outcome (agent estimates): ~1,300–1,550 entries resolve through
phases 0–3; ~1,200–1,450 reach the user (roughly 800–950 articles, 190–280 books,
~70 proceedings/misc, ~25 coordinate cases, 79 errata). The human share is the
biggest uncertainty and shrinks with each route that works; it is reported after
each phase.
