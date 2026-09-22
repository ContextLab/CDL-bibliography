# Local resolution and broader coverage test — September 15, 2026

This follows the [original fifty-entry source-extraction audit](../pilot50/README.md). The full local run finished at **2,206 verified / 4,216 needing review**, up **249 verified entries** from the previous baseline. The original pilot is now **39/50 verified** (19 of its 30 unresolved entries cleared), and the broader sample is **8/50 verified**. This follow-up makes no new LLM calls and records no human approvals. Nothing has been pushed.

[All thirty original-pilot outcomes](pilot-resolution.json), [full-run changes](summary.json), and [backlog run/repeat metrics](backlog-results.json) retain the evidence trail. The full-library pass used 27 publisher requests and cleared 222 entries beyond the two pilot batches. Repetition made zero requests, added zero review records, and preserved prior approvals. SQLite integrity and baseline/queue fingerprint checks passed. **250 tests**, **60/60 documentary benchmark cases**, and bibliography formatting/duplicate validation passed.

## Rules and evidence

- **Final articles with preprints:** a `has-preprint` link can remain advisory only when the citation supplies the final article's own DOI and all author/title/year/journal/volume/page fields match. Other relationships, malformed links, correction flags, missing coordinates and conflicting fields still block. The relationship stays in the evidence. This follows [Crossref's distinction between journal and preprint DOIs](https://www.crossref.org/documentation/schema-library/markup-guide-record-types/posted-content-includes-preprints/).
- **Exact corporate names:** journal publisher comparison recognizes Elsevier versus Elsevier BV/B.V.; MIT Press versus MIT Press - Journals; and Journal of Neurosurgery Publishing Group with/without its parenthesized acronym. Sources: [Elsevier's legal entity](https://linkinghub.elsevier.com/retrieve/dynamic/ihubTerms.jsp), [MIT Press journals](https://direct.mit.edu/journals/pages/browse_by_title), and [AANS's publishing group](https://annualreports.aans.org/aans/journal-of-neurosurgery-publishing-group/). No fuzzy matching, general suffix removal or acquisition-based mapping is allowed. Academic Press, Nature Publishing Group, Plenum Press and Little, Brown remain distinct. Book publisher checks remain literal.
- **Issue labels:** a MEDLINE `Pt N` label can corroborate Crossref issue `N` only with the same DOI, shared ISSN and matching title, ordered authors, journal, year, volume and pages in both records. Supplements and conflicting parts remain blockers. The live example is [Worrell's PubMed record](https://pubmed.ncbi.nlm.nih.gov/15155522/).
- **Publication versus archival dates:** the new Cambridge-specific layer reads the article's own HTML-head metadata. It requires an exact DOI, shared ISSN, complete author/title/venue/volume/page agreement, and an explicit publication year agreeing with Crossref's print year. Only the conflicting-date blocker can be cleared. The two Psychometrika records explicitly separate publication in 1952/1977 from online posting in 2025. Source metadata and document hashes are retained; body references never supply metadata. Duplicate author names remain in order.
- **Discovery checkpoints:** newly found DOI candidates receive secondary lookups even when earlier candidates were already checked. DOI-specific checkpoints avoid repeating old lookups. Secondary and full-text review preserve discovery/research checkpoints. Publisher timeouts, rate limits and server failures remain retryable.

Resolver revision 3 reconsiders unresolved saved evidence once. Current approvals and check times are preserved. The Cambridge layer has its own checkpoint. Every non-key BibTeX edit invalidates verification; cached source responses can still be reused for that recheck. Cite-key-only renames retain verification.

## Corrections, sample and limits

[Corrections](corrections.json) records exact before/after text for nine entries: final DOIs for `MannEtal22`, `GuesMart21`, and `LifaEtal21`; removal of the author affiliation misfiled as an address in `RuggCurr07`; formal proceedings spelling in `TianEtal16a` and `CarvEtal22a`; replacement of `AherBeat81`'s misused organization field with the historical Plenum Press publisher; Grober's print year; and Smolensky's original journal DOI. Ahern remains unresolved because the registry names Springer US. Grober retains its key via the existing formatting exception, which never bypasses source checks.

Eight of the nine corrected entries now verify; the historical Ahern publisher remains unresolved.

The [remaining original-pilot dossier](remaining-pilot.json) records each unresolved gap and required evidence. [Primary source collection](source-results.json) retrieved two useful Cambridge records and recorded ten explicit retrieval gaps. Its offline repeat made zero fetches. Browser-assisted reading does not establish unattended access to blocked pages.

The [wider sample](wide50.json) has ten entries from each of five exclusive strata: books/chapters, other types, weak/missing source identity, multiple conflicts, and single conflicts. Selection uses SHA-256 ordering of `wide50-v1:key` within strata and excludes the original pilot. All fifty selected entries lacked supplied DOIs; only 33 of the unresolved library entries supplied one. This is a stress sample, not a population accuracy estimate or an LLM benchmark.

The initial wider run used 50 expanded title searches and one batch of six new Europe PMC DOI lookups. Six entries verified; repetition made no requests or review records. Publisher metadata exposed two more corrections: `GrobEtal07` mixed a 2007 online date with a 2008 print volume, and `Smol88` needed its journal DOI to disambiguate later book chapters. After correction, **8/50** wider entries verify and **42 remain unresolved**. The corrective run used three registry requests and its repeat used zero. [Initial results](wide-initial-results.json), [corrected results](wide-results.json), and [publisher-stage results](publisher-results.json) preserve the stages.

The assistant checked the six initially accepted wider entries and the two Cambridge corrections against source records. The [manual-to-automated comparison](manual-comparison.json) matches all eight entries on ordered author signatures, DOI, year, volume, issue and pages. [Manual audit](manual-wide-audit.json) records ordered author signatures, DOI and coordinates. This is an assistant source audit, not independent human certification. Publisher-name matching establishes consistency with registry metadata; it does not independently certify every historical imprint.

## Local commands

```bash
# Ordinary path for new/edited entries, including the publisher-date layer:
.venv/bin/python bibcheck.py crossref verify cdl.bib --auto-review

# Bounded discovery/correction test and unchanged repeat:
.venv/bin/python verification/resolution-2026-09-15/run.py wide

# Full cached reassessment plus tested publisher-date lookups:
.venv/bin/python verification/resolution-2026-09-15/run.py backlog --publisher

# Source collection replay without network access:
.venv/bin/python verification/resolution-2026-09-15/collect_sources.py --offline

.venv/bin/python -m pytest -q tests --disable-warnings
.venv/bin/python verification/benchmark/run.py
.venv/bin/python bibcheck.py verify --fname cdl.bib
```

Live commands use the existing local Crossref contact or `CROSSREF_MAILTO`. Run one verifier at a time against the SQLite cache. Production verification exits nonzero while selected citations remain unresolved; this is an evidence gate, not a provider failure. Raw documents and logs stay in ignored `.bibcheck/` storage. Portable artifacts contain metadata, provenance and outcomes, not article text or credentials.
