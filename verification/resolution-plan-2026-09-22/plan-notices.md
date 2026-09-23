# Plan: 101 entries held by "DOI-linked source correction/retraction notice requires adjudication"

Date: 2026-09-22. Read-only analysis; no tracked file, cdl.bib or cache was modified.
Scripts and intermediate data: `scratchpad/notices/` (extract.py, detail.py, classify.py, retscan.py;
extracted.json, detail.json, classified.json, retscan.json, table.md).

## Evidence base

- Source: the latest policy-2 review row for each key in `.bibcheck/verification.sqlite3` (opened `mode=ro`).
  Flags recomputed with the repo's own `auto_review.secondary_notice_flags` (EuropePMC
  `commentCorrectionList`/`isRetracted`/pubType; PMC-JATS `related-article`). Crossref `updated-by`,
  `update-to` and `relation` fields were tabulated from the same candidate records.
- Flag scope (bibcheck/auto_review.py `select_result`): the notice issue is appended when **any**
  candidate DOI is flagged, including rejected search alternatives:
  `+ (["DOI-linked source correction/retraction notice requires adjudication"] if flagged else [])`.
  docs/verification.md already states that "notices for unrelated rejected search candidates do not
  rewrite that approval", but this only protects approvals, not `needs_review` issue lists.
- Notice types seen for flagged DOIs (all 101): EuropePMC "Erratum in" (98 relations), "Erratum for" +
  pubType "Published Erratum" (2, erratum records pulled in as candidates: TompDava17, MoriEtal12),
  JATS `correction-forward` (71), Crossref `updated-by` correction/erratum/addendum (43 keys).
  **Zero** `isRetracted=Y`, zero "Retraction in", zero "Expression of concern" on any flagged DOI.
- Notice bodies: not cached. Only ChanEtal12b has an indexed-text summary
  (verification/completion-2026-09-15/notice-adjudication-leads.json: "The notice corrects the final
  sentence in page 91 section 2.7.2 ... does not describe a bibliographic correction").
  Spot probe (6 requests): EuropePMC core record for erratum PMID 28356398 (delaEtal16) has title only,
  no abstract; PMC efetch of the erratum PMC6596917 has front matter only, `pmc-prop-pdf-only`-style
  (no body); EuropePMC PDF render returned HTTP 403. README already records publisher API returns
  "metadata only". Expect notice bodies to need PDFs/landing pages, i.e. human reading.

## Classification (counts sum to 101)

| class | n | meaning |
|-|-|-|
| M | 22 | Notice belongs to an unrelated search candidate (title sim < 0.8 and author+title both mismatch). Not a notice on the cited work. |
| A | 30 | Flagged DOI is the cited work; every compared field matches (author, title, journal, year, volume, number, pages). Erratum only. |
| B | 38 | Flagged DOI is the cited work; discrepancies are benign or local-field errors (first page only vs range, publisher string, given names/diacritics/suffix, e-numbers, supplement numbering, `others`, Crossref-truncated author list, DOI stuffed into volume/pages). Erratum only. |
| C | 11 | Flagged DOI is the cited work; substantive discrepancy that an erratum could plausibly concern (author spelling/list, title, year, page range). |

By notice type: erratum/correction 79 (A+B+C); retraction 0; expression of concern 0; duplicate
publication 0; mislinked 22 (M). Metadata-affecting vs content-only cannot be told from cached data
for any of the 79 except ChanEtal12b (content-only per indexed text).

Class C detail: RebeEtal02 (Crossref author "Gitleman", entry "Gitelman"; erratum J Neurosci 2003
23(1):1a), VargEtal97 (entry "Connely", source "Connelly"; erratum Science 277:1117), KossEtal99
(Crossref has an extra author token "L."; erratum Science 284:197), delaEtal16 (entry lacks 5th author
Yarkoni; erratum J Neurosci 37:3735), VirtEtal20 (author list count differs), JahaEtal13 (author
surnames/order), LohnKaha13 (title "word frequency effect"), SkraChiu03 (title separator lost),
MarsEtal06 (year 2006 vs 2000), BisbBurg14 (pages 760--766 vs 21-27), WildRugg96 (889--906 vs 889-905).

Extra co-issues: coordinate conflicts on VirtEtal20, ChanEtal12a, FletEtal96, SwalEtal09 (class A but
not clean), MarkEtal95a; PubMed author-suffix conflicts on WittEtal18, JohnEtal98, LeVaEtal08.

## Retractions / expressions of concern

- None among the 101 cited works.
- Library-wide scan of all 6,422 latest cached reviews (retscan.py) for Crossref `updated-by`/`update-to`
  retraction|withdrawal|expression_of_concern|removal, Crossref `relation.retraction`, EuropePMC
  `isRetracted=Y`, "Retraction in"/"Concern" relations: hits only on unrelated search candidates
  (title+author mismatch) for DelgEtal05, KeleFent10 (Savine & Braver 2010 J Neurosci, retracted 2013),
  GapiEtal11 (withdrawn Cochrane protocol), HutcEtal13 (WITHDRAWN NeuroImage 2023 item), ItieTayl04,
  Jell02 (Cell Tissue Res 2004/2005 Jellinger pair), LiuEtal17, OsipEtal08, Zyda05. No cited work in
  cdl.bib carries a retraction in cached evidence. Caveat: coverage is only as good as cached Crossref
  (incl. Retraction Watch-fed `updated-by`) and EuropePMC records; entries whose cited work has no
  DOI/PubMed record were not checkable this way.

## Proposed policy

1. **Code fix, deterministic (M, 22):** attribute a notice to an entry only when the flagged
   candidate is plausibly the cited work: supplied/accepted DOI, or evidence where title OR author
   matches (fail closed: keep the flag if either matches or evidence is missing). All 22 M rows have
   both title and author mismatching; none of A/B/C would be dropped. Add regression tests from real
   cached cases (HarrEtal20 must not inherit SciPy's erratum; BrisEtal02 must not inherit ChanEtal12b's;
   KeleFent10 must not inherit the Savine retraction). The source_notices index still keeps the
   notices. These 22 then fall back into their other groups (no-match / coordinates / suffix).
   Also exclude candidates whose own pubType is "Published Erratum" from being treated as the cited work
   (TompDava17, MoriEtal12 second DOIs).
2. **Never auto-clear a notice.** Notices on the cited work (79) require a named-human acknowledgement,
   because notice bodies are not machine-available and the repo already reopened two premature
   approvals (ChanEtal12b, MenoEtal96) for exactly this.
3. **Status design:** keep the accepted statuses unchanged (`metadata_verified`, `human_verified`).
   Add a `notice_acknowledgement` record: {reviewer, date, notice_dois, notice evidence_hashes from
   `source_notices`, decision, note, fingerprint}. Gate rule: an entry with a known notice passes only if
   (a) metadata is fully matched by deterministic source comparison (or human_verified for its fields)
   AND (b) every current notice evidence hash is acknowledged. A new notice hash, or any entry edit,
   reopens it. Decisions: `keep-content-only` (notice does not change citation metadata),
   `keep-metadata-corrected` (entry already reflects corrected metadata), `fix-entry` (apply correction,
   then re-verify), `replace/remove-citation` (retracted or superseded), `escalate`.
   Retractions/EoCs (none now) get a separate, never-bulk decision and are listed in every `status` report.
   Keep notices visible permanently via a `bibcheck notices` report rather than editing cdl.bib
   (optional: BibTeX `note` annotation, user choice).
4. **Order of work:** fix M scoping -> fix B/C metadata through existing correction pipelines
   (page ranges, given names, local-field errors) so each reaches full metadata match -> batch human
   notice review for A (30) + B (38) + C (11) -> C rows additionally need the erratum PDF read.
   Before review, attempt notice-text retrieval per notice DOI (Crossref record, PubMed erratum record,
   PMC erratum PDF where fetchable, publisher landing page) and cache it; show whatever is found.
5. **Batch review format:** one static HTML page (plus CSV/JSON export) with one row per entry:
   key, BibTeX fields, cited DOI link, per-field match grid (Crossref / PubMed / JATS), notice type(s)
   with links (doi.org for notice DOI, PubMed for erratum PMID, PMC id), cached notice text excerpt
   or "not retrieved", the class and discrepancy, a pre-filled suggested decision, and a decision
   dropdown + note. Sort C first, then B, then A; allow "acknowledge all visible" per class after
   scanning. Reviewer name entered once. Export JSON is imported by a CLI (e.g.
   `bibcheck acknowledge-notices --reviewer "..." --file decisions.json`) that checks fingerprints and
   evidence hashes before writing, exactly like `approve` does.

## Per-key table

### C same work, substantive discrepancy (erratum may bear on it) (11)

| key | flagged DOI | notice refs | discrepancy / note | extra issues |
|-|-|-|-|-|
| BisbBurg14 | 10.1101/lm.032409.113 | Erratum in: Learn Mem. 2014 Feb;21(2):127; JATS correction-forward: PMC3895226 | pages 760--766 vs source 21-27 |  |
| delaEtal16 | 10.1523/jneurosci.4402-15.2016 | Erratum in: J Neurosci. 2017 Mar 29;37(13):3735. doi: 10.1523/JNEUROSCI.0471-17.2017 [PMID 28356398]; JATS correction-forward: PMC6596917 | entry lacks 5th author (Yarkoni) |  |
| JahaEtal13 | 10.1016/j.neuroimage.2013.04.061 | Crossref updated-by erratum: 10.1016/j.neuroimage.2013.12.053; Erratum in: Neuroimage. 2014 Apr 15;90:470-1; JATS correction-forward:  | author surnames/order differ; number |  |
| KossEtal99 | 10.1126/science.284.5411.167 | Erratum in: Science 1999 May 7;284(5416):197 | source has extra author token "L." |  |
| LohnKaha13 | 10.1037/a0033669 | Crossref updated-by correction: 10.1037/a0034164; Erratum in: J Exp Psychol Learn Mem Cogn. 2013 Nov;39(6):1725; JATS correction-forward:  | title "word frequency effect" vs source |  |
| MarsEtal06 | 10.1162/08989290051137459 | Erratum in: J Cogn Neurosci 2000 Nov;12(6):following table of contents | year 2006 vs source 2000 |  |
| RebeEtal02 | 10.1523/jneurosci.22-21-09541.2002 | Erratum in: J Neurosci. 2003 Jan 1;23(1):1a.; JATS correction-forward: PMC6742145 | source author "Gitleman" vs entry "Gitelman" |  |
| SkraChiu03 | 10.1016/s0304-3940(03)00137-x | Erratum in: Neurosci Lett. 2004 Dec 6;372(3):266 | title separator lost ("meaningbehavioral") |  |
| VargEtal97 | 10.1126/science.277.5324.376 | Erratum in: Science 1997 Aug 22; 277(5329):1117 | author "Connely" vs source "Connelly" |  |
| VirtEtal20 | 10.1038/s41592-019-0686-2 | Crossref updated-by correction: 10.1038/s41592-020-0772-5; Erratum in: Nat Methods. 2020 Mar;17(3):352. doi: 10.1038/s41592-020-0772-5. [PMID 32094914]; JATS correction-forward: PMC7056641 | author list count differs | DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation |
| WildRugg96 | 10.1093/brain/119.3.889 | Erratum in: Brain 1996 Aug;119(Pt 4):1416 | pages 889--906 vs 889-905 |  |

### B same work, benign/local-fix discrepancy (38)

| key | flagged DOI | notice refs | discrepancy / note | extra issues |
|-|-|-|-|-|
| AfraEtal06 | 10.1038/nature04982 | Erratum in: Nature. 2006 Oct 5;443(7111):598 | benign/format: author, publisher |  |
| BarEtal06 | 10.1073/pnas.0507062103 | Crossref updated-by correction: 10.1073/pnas.0600325103; Erratum in: Proc Natl Acad Sci U S A. 2006 Feb 21;103(8):3007; JATS correction-forward: PMC1413861 | benign/format: author |  |
| BukaEtal06 | 10.1016/j.tics.2006.02.004 | Erratum in: Trends Cogn Sci. 2006 Jun;10(6):243 | benign/format: author |  |
| BullSpor09 | 10.1038/nrn2575 | Crossref updated-by erratum: 10.1038/nrn2618; Erratum in: Nat Rev Neurosci. 2009 Apr;10(4):312 | benign/format: publisher |  |
| ChowEtal13 | 10.1038/nn.3364 | Crossref updated-by erratum: 10.1038/nn1214-1840c; Erratum in: Nat Neurosci. 2014 Dec;17(12):1840; JATS correction-forward: ; JATS correction-forward: This article has been corrected. See  the correction in  volume 17 on page 1840. | benign/format: author |  |
| ColiEtal18 | 10.1038/s41598-018-31985-3 | Crossref updated-by correction: 10.1038/s41598-018-33559-9; Erratum in: Sci Rep. 2018 Oct 23;8(1):15904. doi: 10.1038/s41598-018-33559-9 [PMID 30349070]; JATS correction-forward: PMC6198003; JATS correction-forward: This article has been corrected. See Sci Rep | local field error: number holds article no.; pages 1--13 |  |
| CotmEtal07 | 10.1016/j.tins.2007.06.011 | Erratum in: Trends Neurosci. 2007 Oct;30(10):489 | benign/format: author |  |
| DamaEtal96 | 10.1038/380499a0 | Crossref updated-by correction: 10.1038/381810b0; Erratum in: Nature 1996 Jun 27;381(6595):810 | benign/format: pages |  |
| DeusEtal06 | 10.1056/nejmoa060281 | Erratum in: N Engl J Med. 2006 Sep 21;355(12):1289 | benign/format: author |  |
| DianEtal07 | 10.1016/j.tics.2007.08.001 | Erratum in: Trends Cogn Sci. 2008 Apr;12(4):128 | local field error: volume holds DOI |  |
| DomnEtal13 | 10.1038/nature11973 | Crossref updated-by erratum: 10.1038/nature12794; Erratum in: Nature. 2013 Dec 19;504(7480):470; JATS correction-forward:  | benign/format: publisher |  |
| EuseEtal09 | 10.1093/brain/awp079 | Erratum in: Brain. 2013 Dec;136(Pt 12):e264; JATS correction-forward: PMC4989338; JATS correction-forward: This article has been corrected. See Brain. 2013 Dec 10;136(12):e264. | benign/format: author |  |
| FreuEtal09 | 10.1001/archneurol.2009.102 | Erratum in: Arch Neurol. 2011 Apr;68(4):421 | benign/format: author, pages |  |
| Glim11 | 10.1073/pnas.1014269108 | Crossref updated-by correction: 10.1073/pnas.1114363108; Erratum in: Proc Natl Acad Sci U S A. 2011 Oct 18;108(42):17568-9; JATS correction-forward: PMC3198375 | benign/format: number |  |
| GomeEtal96 | 10.1523/jneurosci.16-14-04491.1996 | JATS correction-forward: PMC6793823 | benign/format: author, pages |  |
| GrilEtal06b | 10.1038/nn1745 | Crossref updated-by erratum: 10.1038/nn0107-133; Erratum in: Nat Neurosci. 2007 Jan;10(1):133 | benign/format: pages |  |
| HoneEtal12a | 10.1016/j.neuron.2012.08.011 | Erratum in: Neuron. 2012 Nov 8;76(3):668; JATS correction-forward:  | benign/format: author |  |
| InouEtal15 | 10.1371/journal.pone.0128720 | Crossref updated-by correction: 10.1371/journal.pone.0133089; Erratum in: PLoS One. 2015 Jul 13;10(7):e0133089. doi: 10.1371/journal.pone.0133089. [PMID 26167893]; JATS correction-forward: PMC4500552 | benign/format: pages |  |
| JohnEtal98 | 10.1016/s0167-8760(98)00006-3 | Erratum in: Int J Psychophysiol 1998 Nov;30(3):367 | benign/format: author | DOI-linked PubMed author suffix conflicts with the citation |
| KahaEtal06 | 10.1684/j.1950-6945.2006.tb00206.x | Erratum in: Epileptic Disord. 2008 Jun;10(2):191 | benign/format: number, pages |  |
| KlauEtal03 | 10.1038/nature01374 | Crossref updated-by erratum: 10.1038/nature04910; Erratum in: Nature. 2006 Jun 15;441(7095):902 | benign/format: author |  |
| LatiEtal10 | 10.1007/s00426-010-0276-5 | Crossref updated-by correction: 10.1007/s00426-016-0761-6; Erratum in: Psychol Res. 2016 Jul;80(4):727. doi: 10.1007/s00426-016-0761-6 [PMID 26892772] | benign/format: author |  |
| MarkEtal95a | 10.1523/jneurosci.15-11-07079.1995 | JATS correction-forward: PMC6579065 | benign/format: pages | DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation |
| MillEtal03 | 10.1093/cercor/bhg101 | Erratum in: Cereb Cortex. 2005 May;15(5):679; JATS correction-forward:  | benign/format: author |  |
| MonaAbbo11 | 10.1523/jneurosci.1433-11.2011 | Erratum in: J Neurosci. 2011 Jul 27;31(30):11096; JATS correction-forward: PMC6623099 | benign/format: pages |  |
| NayaEtal01 | 10.1126/science.291.5504.661 | Erratum in: Science 2001 Mar 2;291(5509):1703 | benign/format: pages |  |
| NeweEtal01 | 10.1111/1467-9280.00307 | Erratum in: Psychol Sci 2001 Jul;12(4):352 | benign/format: author, publisher |  |
| PalaEtal21 | 10.1038/s41467-021-25280-5 | Crossref updated-by correction: 10.1038/s41467-021-27351-z; Erratum in: Nat Commun. 2021 Dec 8;12(1):7265. doi: 10.1038/s41467-021-27351-z [PMID 34880229]; JATS correction-forward: PMC8654943; JATS correction-forward: This article has been corrected. See Nat C | local field error: pages holds doi URL; article no. 5475 |  |
| ParkEtal08 | 10.1101/lm.878908 | JATS correction-forward: PMC2505323 | benign/format: pages, publisher |  |
| PurcEtal10 | 10.1037/a0020311 | Crossref updated-by correction: 10.1037/a0021906; Crossref updated-by correction: 10.1037/a0022305; Erratum in: Psychol Rev. 2010 Oct;117(4):following 1143; Erratum in: Psychol Rev. 2011 Jan;118(1):134; Erratum in: Psychol Rev. 2011 Jan;118(1):96; JATS correct | benign/format: author |  |
| ShapEtal06 | 10.1016/j.conb.2006.08.017 | Crossref updated-by erratum: 10.1016/j.conb.2007.04.011; Erratum in: Curr Opin Neurobiol. 2007 Jun;17(3):394 | benign/format: pages |  |
| StarDava06 | 10.1523/jneurosci.2877-06.2006 | Erratum in: J Neurosci. 2006 Sep 20;26(38):9836; JATS correction-forward: PMC6674442 | benign/format: pages |  |
| TompDava17 | 10.1016/j.neuron.2017.09.005 | Crossref updated-by addendum: 10.1016/j.neuron.2019.12.021; Crossref updated-by erratum: 10.1016/j.neuron.2019.12.020; Erratum in: Neuron. 2020 Jan 8;105(1):199-200. doi: 10.1016/j.neuron.2019.12.020 [PMID 31917954]; JATS correction-forward: 31917954 | benign/format: pages; also flagged erratum-record DOI 10.1016/j.neuron.2019.12.020 |  |
| TonoKoch08 | 10.1196/annals.1440.004 | Erratum in: Ann N Y Acad Sci. 2011 Apr;1225:200 | benign/format: publisher |  |
| WangBuzs96 | 10.1523/jneurosci.16-20-06402.1996 | JATS correction-forward: PMC6792948 | benign/format: author |  |
| WheeEtal00 | 10.1073/pnas.97.20.11125 | Crossref updated-by correction: 10.1073/pnas.0400883101; Erratum in: Proc Natl Acad Sci U S A. 2004 Apr 6;101(14):5181; JATS correction-forward: PMC387398 | benign/format: pages |  |
| WimbEtal15 | 10.1038/nn.3973 | Crossref updated-by correction: 10.1038/s41593-018-0220-3; Erratum in: Nat Neurosci. 2018 Oct;21(10):1493. doi: 10.1038/s41593-018-0220-3. [PMID 30111872]; JATS correction-forward: 30111872; JATS correction-forward: This article has been corrected. See Nat Neu | benign/format: pages |  |
| WittEtal18 | 10.1038/s41593-018-0148-7 | Crossref updated-by correction: 10.1038/s41593-018-0224-z; Erratum in: Nat Neurosci. 2019 Jan;22(1):143. doi: 10.1038/s41593-018-0224-z. [PMID 30127431]; JATS correction-forward: PMC7358895 | benign/format: author | DOI-linked PubMed author suffix conflicts with the citation |

### A same work, all fields match (30)

| key | flagged DOI | notice refs | discrepancy / note | extra issues |
|-|-|-|-|-|
| BenjEtal12 | 10.1037/a0024786 | Crossref updated-by correction: 10.1037/a0031162; Erratum in: Psychol Aging. 2012 Dec;27(4):824; JATS correction-forward:  | all compared fields match |  |
| BoucEtal13 | 10.1038/nature11911 | Crossref updated-by erratum: 10.1038/nature12182; Erratum in: Nature. 2013 Jun 27;498(7455):526; JATS correction-forward:  | all compared fields match |  |
| BuchDEsp09 | 10.1093/cercor/bhn186 | Erratum in: Cereb Cortex. 2009 Dec;19(12):3030; JATS correction-forward: PMC2774402; JATS correction-forward: This article has been corrected. See Cereb Cortex. 2009 Dec;19(12):3030. | all compared fields match |  |
| CalhEtal01 | 10.1002/hbm.1024 | Crossref updated-by correction: 10.1002/hbm.70007; Erratum in: Hum Brain Mapp. 2024 Aug 15;45(12):e70007. doi: 10.1002/hbm.70007 [PMID 39189682]; JATS correction-forward: PMC11348401 | all compared fields match |  |
| ChanEtal12b | 10.1016/j.brainres.2012.02.068 | Erratum in: Brain Res. 2012 Aug 27;1470:159 | all compared fields match |  |
| DAleEtal03 | 10.1109/tbme.2003.810706 | Erratum in: IEEE Trans Biomed Eng. 2003 Aug;50(8):1041 | all compared fields match |  |
| Farr12 | 10.1037/a0027371 | Crossref updated-by correction: 10.1037/a0030031; Erratum in: Psychol Rev. 2012 Oct;119(4):899 | all compared fields match |  |
| GazzEtal05 | 10.1038/nn1543 | Crossref updated-by erratum: 10.1038/nn1205-1791c; Erratum in: Nat Neurosci. 2005 Dec;8(12):1791 | all compared fields match |  |
| HubeEtal01 | 10.1037/0033-295x.108.1.149 | Erratum in: Psychol Rev 2001 Jul;108(3):652 | all compared fields match |  |
| KeleFent10 | 10.1371/journal.pbio.1000403 | Crossref updated-by correction: 10.1371/journal.pbio.1002100; Erratum in: PLoS Biol. 2015 Mar 11;13(3):e1002100. doi: 10.1371/journal.pbio.1002100 [PMID 25761137]; JATS correction-forward: PMC4356546 | all compared fields match |  |
| LangEtal15 | 10.1371/journal.pone.0130834 | Crossref updated-by correction: 10.1371/journal.pone.0134073; Erratum in: PLoS One. 2015 Jul 21;10(7):e0134073. doi: 10.1371/journal.pone.0134073 [PMID 26196149]; JATS correction-forward: PMC4509756 | all compared fields match |  |
| MankEtal12 | 10.1073/pnas.1214107109 | Crossref updated-by correction: 10.1073/pnas.1502758112; Erratum in: Proc Natl Acad Sci U S A. 2015 Mar 10;112(10):E1169. doi: 10.1073/pnas.1502758112 [PMID 25713125]; JATS correction-forward: PMC4364179 | all compared fields match |  |
| MaroIvan05 | 10.1016/j.tics.2005.04.010 | Crossref updated-by erratum: 10.1016/j.tics.2005.05.006; Erratum in: Trends Cogn Sci. 2005 Sep;9(9):415 | all compared fields match |  |
| MenoEtal96 | 10.1016/0013-4694(95)00206-5 | Erratum in: Electroencephalogr Clin Neurophysiol 1996 Mar;98(3):228 | all compared fields match |  |
| MoriEtal12 | 10.1016/j.tins.2012.04.009 | Crossref updated-by erratum: 10.1016/j.tins.2017.05.006; Erratum in: Trends Neurosci. 2017 Jul;40(7):453. doi: 10.1016/j.tins.2017.05.006 [PMID 28571615] | all compared fields match; also flagged erratum-record DOI 10.1016/j.tins.2017.05.006 |  |
| NasrEtal05 | 10.1111/j.1532-5415.2005.53221.x | Crossref updated-by correction: 10.1111/jgs.15925; Erratum in: J Am Geriatr Soc. 2019 Sep;67(9):1991. doi: 10.1111/jgs.15925 [PMID 31493356] | all compared fields match |  |
| NimoEtal08 | 10.3758/brm.40.2.457 | Crossref updated-by erratum: 10.3758/s13428-017-0853-2; Erratum in: Behav Res Methods. 2010 Feb;42(1):363 | all compared fields match |  |
| NosoPalm97 | 10.1037/0033-295x.104.2.266 | Crossref updated-by correction: 10.1037/0033-295x.115.2.446; Erratum in: Psychol Rev. 2008 Apr;115(2):446 | all compared fields match |  |
| RuthEtal21 | 10.1113/ep089074 | Crossref updated-by correction: 10.1113/ep090239; Erratum in: Exp Physiol. 2022 Jan;107(1):94. doi: 10.1113/EP090239 [PMID 34927783] | all compared fields match |  |
| RutiEtal08 | 10.1073/pnas.0706015105 | Crossref updated-by correction: 10.1073/pnas.0805446105; Erratum in: Proc Natl Acad Sci U S A. 2008 Aug 5;105(31):11032; JATS correction-forward: PMC2504827 | all compared fields match |  |
| SahaDela05 | 10.1037/0278-7393.31.4.789 | Crossref updated-by correction: 10.1037/0278-7393.31.5.1164; Erratum in: J Exp Psychol Learn Mem Cogn. 2005 Sep;31(5):1164 | all compared fields match |  |
| SohnEtal00 | 10.1073/pnas.240460497 | Crossref updated-by correction: 10.1073/pnas.081083198; Crossref updated-by correction: 10.1073/pnas.081087498; Erratum in: Proc Natl Acad Sci U S A 2001 Mar 27;98(7):4276; JATS correction-forward: PMC55943 | all compared fields match |  |
| Squi92 | 10.1037/0033-295x.99.2.195 | Crossref updated-by correction: 10.1037/0033-295x.99.3.582; Erratum in: Psychol Rev 1992 Jul;99(3):582 | all compared fields match |  |
| SwalEtal09 | 10.1037/a0015631 | Crossref updated-by correction: 10.1037/a0022160; Erratum in: J Exp Psychol Gen. 2011 Feb;140(1):140; JATS correction-forward:  | all compared fields match | DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation |
| SzpuEtal08 | 10.1037/a0013082 | Crossref updated-by correction: 10.1037/a0014896; Erratum in: J Exp Psychol Learn Mem Cogn. 2009 Jan;35(1):156 | all compared fields match |  |
| TheoFish04 | 10.1016/s1474-4422(03)00664-1 | Erratum in: Lancet Neurol. 2004 Jun;3(6):332 | all compared fields match |  |
| WeidEtal19 | 10.1037/xge0000480 | Crossref updated-by correction: 10.1037/xge0000604; Erratum in: J Exp Psychol Gen. 2019 Apr;148(4):782. doi: 10.1037/xge0000604 [PMID 30973266]; JATS correction-forward: 30973266 | all compared fields match |  |
| YartUlan13 | 10.1126/science.1235338 | Erratum in: Science. 2013 Nov 1;342(6158):559 | all compared fields match |  |
| ZagaEtal13a | 10.1016/j.mcn.2013.07.011 | Crossref updated-by erratum: 10.1016/j.mcn.2017.12.007; Erratum in: Mol Cell Neurosci. 2018 Apr;88:353. doi: 10.1016/j.mcn.2017.12.007 [PMID 29276073] | all compared fields match |  |
| ZhanEtal13 | 10.1126/science.1232627 | Erratum in: Science. 2013 Apr 19;340(6130):273 | all compared fields match |  |

### M notice on unrelated candidate (22)

| key | flagged DOI | notice refs | discrepancy / note | extra issues |
|-|-|-|-|-|
| BakeEtal07 | 10.1038/nn1745 | Erratum in: Nat Neurosci. 2007 Jan;10(1):133 | notice belongs to unrelated search candidate: 10.1038/nn1745 (High-resolution imaging reveals highly selective nonface clu) |  |
| BrisEtal02 | 10.1016/j.brainres.2012.02.068 | Erratum in: Brain Res. 2012 Aug 27;1470:159 | notice belongs to unrelated search candidate: 10.1016/j.brainres.2012.02.068 (The effects of acute exercise on cognitive performance: A me) |  |
| CartWang07 | 10.1093/cercor/bhg101 | Erratum in: Cereb Cortex. 2005 May;15(5):679; JATS correction-forward:  | notice belongs to unrelated search candidate: 10.1093/cercor/bhg101 (A Recurrent Network Model of Somatosensory Parametric Workin) |  |
| ChanEtal12a | 10.1523/jneurosci.4402-15.2016 | Erratum in: J Neurosci. 2017 Mar 29;37(13):3735. doi: 10.1523/JNEUROSCI.0471-17.2017 [PMID 28356398]; JATS correction-forward: PMC6596917 | notice belongs to unrelated search candidate: 10.1523/jneurosci.4402-15.2016 (Large-Scale Meta-Analysis of Human Medial Frontal Cortex Rev) | DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation |
| ChanEtal20 | 10.1523/jneurosci.4402-15.2016 | Erratum in: J Neurosci. 2017 Mar 29;37(13):3735. doi: 10.1523/JNEUROSCI.0471-17.2017 [PMID 28356398]; JATS correction-forward: PMC6596917 | notice belongs to unrelated search candidate: 10.1523/jneurosci.4402-15.2016 (Large-Scale Meta-Analysis of Human Medial Frontal Cortex Rev) |  |
| DyneEtal90 | 10.1523/jneurosci.2877-06.2006 | Erratum in: J Neurosci. 2006 Sep 20;26(38):9836; JATS correction-forward: PMC6674442 | notice belongs to unrelated search candidate: 10.1523/jneurosci.2877-06.2006 (Differential Encoding Mechanisms for Subsequent Associative ) |  |
| FletEtal96 | 10.1037/xge0000480 | Erratum in: J Exp Psychol Gen. 2019 Apr;148(4):782. doi: 10.1037/xge0000604 [PMID 30973266]; JATS correction-forward: 30973266 | notice belongs to unrelated search candidate: 10.1037/xge0000480 (Neural activity reveals interactions between episodic and se) | DOI-linked publisher/PubMed article coordinates conflict with or are missing from the citation |
| GardEtal06 | 10.1109/tbme.2003.810706 | Erratum in: IEEE Trans Biomed Eng. 2003 Aug;50(8):1041 | notice belongs to unrelated search candidate: 10.1109/tbme.2003.810706 (Epileptic seizure prediction using hybrid feature selection ) |  |
| HansSchm10 | 10.1038/nn1745 | Erratum in: Nat Neurosci. 2007 Jan;10(1):133 | notice belongs to unrelated search candidate: 10.1038/nn1745 (High-resolution imaging reveals highly selective nonface clu) |  |
| HarrEtal20 | 10.1038/s41592-019-0686-2 | Erratum in: Nat Methods. 2020 Mar;17(3):352. doi: 10.1038/s41592-020-0772-5. [PMID 32094914]; JATS correction-forward: PMC7056641 | notice belongs to unrelated search candidate: 10.1038/s41592-019-0686-2 (SciPy 1.0: fundamental algorithms for scientific computing i) |  |
| JacoEtal05a | 10.1093/brain/119.3.889 | Erratum in: Brain 1996 Aug;119(Pt 4):1416 | notice belongs to unrelated search candidate: 10.1093/brain/119.3.889 (An event-related potential study of recognition memory with ) |  |
| JobsEtal10 | 10.1016/s1474-4422(03)00664-1 | Erratum in: Lancet Neurol. 2004 Jun;3(6):332 | notice belongs to unrelated search candidate: 10.1016/s1474-4422(03)00664-1 (Brain stimulation for epilepsy) |  |
| KahaGree93 | 10.1037/a0033669 | Erratum in: J Exp Psychol Learn Mem Cogn. 2013 Nov;39(6):1725; JATS correction-forward:  | notice belongs to unrelated search candidate: 10.1037/a0033669 (Parametric effects of word frequency in memory for mixed fre) |  |
| LeVaEtal08 | 10.1038/nature01374 | Erratum in: Nature. 2006 Jun 15;441(7095):902 | notice belongs to unrelated search candidate: 10.1038/nature01374 (Brain-state- and cell-type-specific firing of hippocampal in) | DOI-linked PubMed author suffix conflicts with the citation |
| LittEtal01 | 10.1109/tbme.2003.810706 | Erratum in: IEEE Trans Biomed Eng. 2003 Aug;50(8):1041 | notice belongs to unrelated search candidate: 10.1109/tbme.2003.810706 (Epileptic seizure prediction using hybrid feature selection ) |  |
| LongKaha12a | 10.1523/jneurosci.2877-06.2006 | Erratum in: J Neurosci. 2006 Sep 20;26(38):9836; JATS correction-forward: PMC6674442 | notice belongs to unrelated search candidate: 10.1523/jneurosci.2877-06.2006 (Differential Encoding Mechanisms for Subsequent Associative ) |  |
| OtteEtal01 | 10.1101/lm.878908 | JATS correction-forward: PMC2505323 | notice belongs to unrelated search candidate: 10.1101/lm.878908 (Effects of study task on the neural correlates of source enc) |  |
| ReynRich05 | 10.1093/brain/119.3.889 | Erratum in: Brain 1996 Aug;119(Pt 4):1416 | notice belongs to unrelated search candidate: 10.1093/brain/119.3.889 (An event-related potential study of recognition memory with ) |  |
| Skan98 | 10.1016/s0304-3940(03)00137-x | Erratum in: Neurosci Lett. 2004 Dec 6;372(3):266 | notice belongs to unrelated search candidate: 10.1016/s0304-3940(03)00137-x (Dimensions of affective semantic meaning — behavioral and ev) |  |
| SterEtal96a | 10.1523/jneurosci.22-21-09541.2002 | Erratum in: J Neurosci. 2003 Jan 1;23(1):1a.; JATS correction-forward: PMC6742145 | notice belongs to unrelated search candidate: 10.1523/jneurosci.22-21-09541.2002 (Neural Correlates of Successful Encoding Identified Using Fu) |  |
| WiggEtal99 | 10.1037/xge0000480 | Erratum in: J Exp Psychol Gen. 2019 Apr;148(4):782. doi: 10.1037/xge0000604 [PMID 30973266]; JATS correction-forward: 30973266 | notice belongs to unrelated search candidate: 10.1037/xge0000480 (Neural activity reveals interactions between episodic and se) |  |
| WildEtal95 | 10.1093/brain/119.3.889 | Erratum in: Brain 1996 Aug;119(Pt 4):1416 | notice belongs to unrelated search candidate: 10.1093/brain/119.3.889 (An event-related potential study of recognition memory with ) |  |
