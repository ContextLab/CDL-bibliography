# Continuation after arXiv002

**Update 2026-09-22 (afternoon):** the four arXiv corrections below (ConnEtal18 v5
pin, GongEtal25 v3 pin, FangEtal24 title, ReddEtal18 title) were applied and
verified as batch arxivfix001; see the README section of that name. Stable export
is now 3,669 / 2,753, 854 edit operations. The remaining text is the pre-batch plan.

**Paused at the user's request on 2026-09-22. Start with
[the handoff](PAUSED-2026-09-22.md) when asked to resume.** Exact-version sources
for proposed ConnEtal18 v5 and GongEtal25 v3 pins have now been collected and
pass preflight, with a zero-request repeat. Neither pin is applied or approved
in the main cache; no new correction batch has been staged.

Stable export: 3,665 metadata_verified / 2,757 needs_review, all 6,422 original
keys retained. No bibliography edits this continuation; 850 cumulative edit
operations remain. Policy 2, resolver 27, catalogue 6, PMC 2, bioRxiv 2, arXiv 1.
Full suite: 1,090 passed; documentary benchmark: 60/60. Main cache writer stopped.
Fresh restore result is recorded in restore-latest.json. No commits or pushes.

The arXiv route is now integrated in verify --auto-review and portable snapshots.
Pilot 001 added three approvals; expansion 002 added 24. All positives were
personally spot-checked; WietKiel19 and BrowEtal20 also match visually inspected
original PDFs. Collection and production repeats used zero network requests;
production repeats wrote zero reviews. All prior approvals remained identical.

## Immediate source work

28 preprint leads remain: 15 arXiv, seven bioRxiv, six PsyArXiv. Use the filtered
private remaining-preprints-after-arxiv002.json, not the old 63-entry list.
The filtered expanded-shortlist-after-arxiv002.json has 28 remaining PDF leads.

The new source audits identify concrete arXiv follow-ups:
- ConnEtal18: local PDF side stamp is arXiv:1705.02364v5, 8 July 2018. Its title
  and five-person byline match. Exact v5 API/HTML is now saved in
  arxiv-pins001-sources.json. Inspect it before staging an explicit v5 identifier,
  preserving year 2018. Do not blindly substitute initial year 2017.
- GongEtal25: current v3 is from 2025, first submission 2024; exact v3 sources
  are now saved in arxiv-pins001-sources.json. Inspect before pinning, preserving
  year 2025 if the exact-version evidence supports it.
- FangEtal24: source title includes (DiTs), missing from citation.
- ReddEtal18: title was accidentally duplicated with an extra word authors.
- CerEtal18: original PDF v2 confirms Sheng-yi Kong (hyphenated), and prints
  Mario Guajardo-Céspedes with an accent. Review the entire byline before any
  correction; a change to S-Y alone does not settle the printed surname detail.
- AlvaEtal05: original v2 PDF confirms title typos k-corr and visualiztion, but
  prints Ignacio rather than repository Jose Ignacio. Explicit source hold is
  attached in the main cache; do not add J solely to satisfy registry metadata.
- JianEtal24: API full name Diego de las Casas differs in given/family partition
  from HTML Casas, Diego de las. This is a parser/source-structure issue to
  resolve conservatively, not evidence of another person.
- KhanEtal25: repository adds Inception Labs before 12 people. Corporate-author
  handling needs documentary evidence; do not parse the organization as a person.
- LiuEtal24 and YangEtal24: corporate authors and incomplete local lists remain.
- VodrEtal16 and ZhenEtal19: later versions have added authors; retrieve earlier
  version metadata before changing bylines or pinning the originally cited work.
- LiEtal24b, MillEtal07b and Rove14: missing/incomplete identifiers need discovery.

Known arXiv negative control 1805.02682 retains its title while v2 is withdrawn;
old v1 is not withdrawn. Controls stay in tests only. Piantadosi-Hill v1 actually
misspells Piantadosi as Piantasodi; current v2 repairs it. Do not borrow latest
metadata to approve older explicit versions.

BioRxiv holds: ZimaMann21 API reverses author order; BetzEtal19 API partitions
Zamani Esfahlani differently. GoldEtal21, JainHuth18, TsitEtal19 and XieEtal21
have multiple unpinned versions. AbdeEtal21 lacks an identifier. PsyArXiv still
needs a separately validated repository route.

The PDF originals remain read-only. MeyeEtal18 needs final-version year evidence;
RigoEtal13 and Bar04 need historical publisher evidence. Buzs06's printed book
corroborates its citation but MARC's G. heading versus György and publication-place
evidence need a principled source rule. Retain accents and full names.
