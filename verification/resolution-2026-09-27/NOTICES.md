# Notice classification (2026-09-27)

Each of the 87 held entries in `notices.json` was checked against the notice itself (publisher page, PMC PDF, PsycNET record, Crossref/Europe PMC/PubMed). Row-level detail with verbatim quotes and URLs: `notices-classified.json` (91 rows; some entries have 2 notices).

## Counts (per entry, most serious class)

| class | entries |
|-|-|
| retraction | 0 |
| expression_of_concern | 0 |
| metadata_correction | 5 |
| unread | 23 |
| coordinate_conflict | 2 |
| cited_work_is_notice | 1 |
| new_version | 4 |
| unrelated | 1 |
| no_notice | 3 |
| content_only | 48 |

- Retractions / expressions of concern: **none**. No cited DOI has a Crossref retraction/expression_of_concern update or Europe PMC `isRetracted`.
- metadata_correction: all 5 corrections are already in cdl.bib HEAD. No edit is needed. In two of them (BabiEtal04, LatiEtal10) the publisher notice outranks Crossref's uncorrected author record.
- unread: the notice text could not be retrieved. Elsevier/Cell Press blocks scripts and shows a CAPTCHA to the browser, and Science and SAGE are paywalled. Four old errata (HubeEtal01, KahaEtal06, MarsEtal00, KossEtal99/VargEtal97) have no registered notice DOI. These still need a human read.
- no_notice / unrelated: the entry is held by a PubMed author-suffix (`Jr`) record, not by a notice. For Este91 that record belongs to an unrelated candidate.

## Entries needing attention

| key | class | point |
|-|-|-|
| BarEtal06 | metadata_correction | author A M Schmidt -> A M Schmid (entry already Schmid) |
| BabiEtal04 | metadata_correction | forenames/surnames transposed in print; entry already correct, Crossref still transposed |
| LatiEtal10 | metadata_correction | author F Dagata -> F D'Agata (entry already D'Agata; Crossref still Dagata) |
| BisbBurg14 | metadata_correction | issue repaginated; pages -> 21--27 (entry already 21--27) |
| RosaEtal07 | metadata_correction | Kissela forename Bret -> Brett (entry uses initial B; no change) |
| HeniEtal19 | coordinate_conflict | pages missing; Crossref=PubMed=PMC give ENEURO.0306-19.2019, so add it |
| Fred04 | coordinate_conflict | PubMed 1367-1378 vs Crossref 1367-1377; Crossref wins, entry right |
| GrilEtal06b | content_only | corrigendum withdraws the headline claim (FFA nonface-selective voxels); Figs 4 and 8 invalid. Not a retraction |
| SwalEtal09 | content_only | covariate error; a secondary conclusion weakened |
| TompDava17 | unread | erratum (2 pp) plus an Editorial Note (Crossref 'addendum'); text not retrievable, so read before approving |
| YoneJaco97 | cited_work_is_notice | the entry cites the correction notice to YoneJaco96a itself |
| RubiEtal17, ThomEtal18, TokeSomm19, VanSEtal18 | new_version | Crossref new_version points to the same DOI: PLOS replaced the uncorrected proof with the version of record |

## Per-entry table

| key | notice | class |
|-|-|-|
| AfraEtal06 | 10.1038/nature05153 | content_only |
| BabiEtal04 | 10.1111/j.1460-9568.2004.03705.x | metadata_correction |
| BarEtal06 | 10.1073/pnas.0600325103 | metadata_correction |
| BenjEtal12 | 10.1037/a0031162 | content_only |
| BisbBurg14 | - | metadata_correction |
| BoucEtal13 | 10.1038/nature12182 | content_only |
| Brun04 | 10.1016/j.jneumeth.2005.03.001 | unread |
| BuchDEsp09 | 10.1093/cercor/bhp204 | content_only |
| BukaEtal06 | 10.1016/j.tics.2006.04.006 | unread |
| BullSpor09 | 10.1038/nrn2618 | content_only |
| CalhEtal01 | 10.1002/hbm.70007 | content_only |
| ChowEtal13 | 10.1038/nn1214-1840c | content_only |
| ColiEtal18 | 10.1038/s41598-018-33559-9 | content_only |
| CotmEtal07 | 10.1016/j.tins.2007.09.001 | unread |
| DAleEtal03 | 10.1109/tbme.2003.815899 | content_only |
| DamaEtal96 | 10.1038/381810b0 | content_only |
| delaEtal16 | 10.1523/JNEUROSCI.0471-17.2017 | content_only |
| DeusEtal06 | 10.1056/nejmx060054 | content_only |
| DianEtal07 | 10.1016/j.tics.2008.03.001 | unread |
| DomnEtal13 | 10.1038/nature12794 | content_only |
| Eich85 | 10.1037/h0090456 | content_only |
| Este91 | - | unrelated |
| EuseEtal09 | 10.1093/brain/awr162 | content_only |
| Farr12 | 10.1037/a0030031 | content_only |
| Fred04 | - | coordinate_conflict |
| FreuEtal09 | 10.1001/archneurol.2011.75 | content_only |
| FrieEtal99 | - | no_notice |
| GazzEtal05 | 10.1038/nn1205-1791c | content_only |
| Glim11 | 10.1073/pnas.1114363108 | content_only |
| GomeEtal96 | 10.1523/JNEUROSCI.17-14-j0001.1997 | content_only |
| GonsPall00 | 10.1038/82837 | content_only |
| GrilEtal06b | 10.1038/nn0107-133 | content_only |
| HeniEtal19 | - | coordinate_conflict |
| HoneEtal12a | 10.1016/j.neuron.2012.10.024 | unread |
| HubeEtal01 | - | unread |
| InouEtal15 | 10.1371/journal.pone.0133089 | content_only |
| JahaEtal13 | 10.1016/j.neuroimage.2013.12.053 | unread |
| KahaEtal06 | - | unread |
| KeleFent10 | 10.1371/journal.pbio.1002100 | content_only |
| KlauEtal03 | 10.1038/nature04910 | content_only |
| KossEtal99 | - | unread |
| LangEtal15 | 10.1371/journal.pone.0134073 | content_only |
| LatiEtal10 | 10.1007/s00426-016-0761-6 | metadata_correction |
| LohnKaha13 | 10.1037/a0034164 | content_only |
| MaroIvan05 | 10.1016/j.tics.2005.05.006 | unread |
| MarsEtal00 | - | unread |
| McDoEtal10 | - | no_notice |
| McKiNoso96 | 10.1037/0096-1523.24.1.339 | content_only |
| MenoEtal96 | 10.1016/0013-4694(96)80250-1 | unread |
| MillEtal03 | 10.1093/cercor/bhi102 | content_only |
| MoriEtal12 | 10.1016/j.tins.2017.05.006 | unread |
| Murd56 | - | no_notice |
| NasrEtal05 | 10.1111/jgs.15925 | content_only |
| NayaEtal01 | 10.1126/science.291.5509.1703b | unread |
| NeweEtal01 | 10.1111/1467-9280.00365 | unread |
| NimoEtal08 | 10.3758/s13428-017-0853-2 | content_only |
| NosoPalm97 | 10.1037/0033-295x.115.2.446 | content_only |
| PalaEtal21 | 10.1038/s41467-021-27351-z | content_only |
| ParkEtal08 | - | content_only |
| Pike84 | 10.1037/h0090457 | content_only |
| PurcEtal10 | 10.1037/a0022305 | content_only |
| PurcEtal10 | 10.1037/a0021906 | content_only |
| Pyly73 | 10.1037/h0020008 | content_only |
| RosaEtal07 | 10.1161/circulationaha.107.181865 | content_only |
| RosaEtal07 | 10.1161/cir.0b013e3181e65a91 | metadata_correction |
| RubiEtal17 | 10.1371/journal.pcbi.1005649 | new_version |
| RuthEtal21 | 10.1113/ep090239 | content_only |
| SahaDela05 | 10.1037/0278-7393.31.5.1164 | content_only |
| ShapEtal06 | 10.1016/j.conb.2007.04.011 | unread |
| SkraChiu03 | 10.1016/j.neulet.2004.09.034 | unread |
| Squi92 | 10.1037/0033-295x.99.3.582 | content_only |
| SwalEtal09 | 10.1037/a0022160 | content_only |
| SzpuEtal08 | 10.1037/a0014896 | content_only |
| TheoFish04 | 10.1016/s1474-4422(04)00765-3 | unread |
| ThomEtal18 | 10.1371/journal.pcbi.1006196 | new_version |
| TokeSomm19 | 10.1371/journal.pcbi.1006807 | new_version |
| TompDava17 | 10.1016/j.neuron.2019.12.020 | unread |
| TompDava17 | 10.1016/j.neuron.2019.12.021 | unread |
| TonoKoch08 | 10.1111/j.1749-6632.2011.06029.x | content_only |
| VanSEtal18 | 10.1371/journal.pcbi.1007031 | content_only |
| VanSEtal18 | 10.1371/journal.pcbi.1006632 | new_version |
| VargEtal97 | - | unread |
| WeidEtal19 | 10.1037/xge0000604 | content_only |
| WildRugg96 | 10.1093/brain/119.4.1415-a | content_only |
| WimbEtal15 | 10.1038/s41593-018-0220-3 | content_only |
| WittEtal18 | 10.1038/s41593-018-0224-z | content_only |
| YartUlan13 | 10.1126/science.342.6158.559-b | unread |
| YoneJaco96a | 10.1037/0096-3445.126.1.18 | content_only |
| YoneJaco97 | 10.1037/0096-3445.126.1.18 | cited_work_is_notice |
| ZagaEtal13a | 10.1016/j.mcn.2017.12.007 | unread |
| ZhanEtal13 | 10.1126/science.340.6130.273-b | unread |

## Mop-up classification (2026-09-27, later)

Rows appended to `notices-classified.json` (now 109 rows). Each notice was read at its URL; the quotes were
re-checked against a scripted fetch of the same page (PMC pages need a browser user agent; the text matched
up to whitespace; ChanEtal12's corrigendum surfaced once its post-check residue was settled). No retraction or expression of concern was found: no Crossref `update-to`/`updated-by` of
that type and no Europe PMC `isRetracted`/"Retraction in"/"Expression of concern in" on any cited DOI.

| key | notice | class | point |
|-|-|-|-|
| BarrEtal18 | 10.1371/journal.pbio.2005479 | new_version | PLOS replaced the uncorrected proof under the same DOI; no citation field changes (entry 16(7) e2005479 matches PMC) |
| JohnEtal98 | 10.1016/s0167-8760(98)00054-3 | unread | Int J Psychophysiol 30(3):367 "Erratum"; ScienceDirect captcha, Elsevier API needs a key. Not a retraction |
| MankEtal12 | 10.1073/pnas.1502758112 | content_only | Fig. 5 and one passage |
| MarkEtal95a | 10.1523/jneurosci.16-09-j0001.1996 | content_only | three reference-list corrections |
| MonaAbbo11 | - (PMC6623099) | metadata_correction | "Larry F. Abbott" should have read "L. F. Abbott"; entry already L F Abbott |
| RebeEtal02 | 10.1523/jneurosci.23-01-00001.2003 | metadata_correction | third author Gitleman -> Gitelman; entry already D R Gitelman |
| RutiEtal08 | 10.1073/pnas.0805446105 | content_only | Fig. 2 panels E and F transposed |
| SohnEtal00 | 10.1073/pnas.081083198 | content_only | sign of x coordinates in Tables 2 and 3 |
| SohnEtal00 | 10.1073/pnas.081087498 | unrelated | the correction for Le et al. (PMC55944) on the same page; Crossref deposited the page's targets on each notice |
| StarDava06 | - (PMC6674442) | content_only | overlapping lettering in Figure 4 |
| WangBuzs96 | 10.1523/jneurosci.18-17-j0002.1998 | content_only | Figure 11 current values |
| WheeEtal00 | 10.1073/pnas.0400883101 | content_only | Fig. 3f plotted from another region; "does not affect the conclusions" |
| VirtEtal20 | 10.1038/s41592-020-0772-5 | content_only | corresponding-author marks, an affiliation, wording; the author list is unchanged |
| PurcEtal10 | - (third link) | unread | PubMed "Psychol Rev. 2010 Oct;117(4):following 1143"; Crossref and PsycNET list only the two classified notices. Not a retraction |
| LeVaEtal08 | - | no_notice | PubMed author suffix 'Engel J Jr'; suffixes are never added |
| PfurEtal96 | - | no_notice | PubMed author suffix 'Stancák A Jr'; suffixes are never added |
| Buzs02b | - | unrelated | author-suffix record of an unrelated search candidate (Bragin et al. 1999, Hippocampus) |
| ChanEtal12 | 10.1016/j.brainres.2012.06.039 | unread | Brain Res 1470:159 corrigendum; ScienceDirect 403 to scripts and the automated browser. Not a retraction. For the user: its Crossref title quotes the article as 'A meta-analytic review'; the article prints 'a meta-analysis' |

### Record identities for notices with no DOI

A row without a notice DOI now names the exact DOI-linked records it was classified beside, in `records`
(`[{doi, identity}]`, the identity the cache's notice, PubMed-suffix and article-locator tables store; see
`verification/research-route-2026-09-27/README.md`, "Notices with no DOI: record identity"). The rows named
this way: BisbBurg14, ParkEtal08, HubeEtal01, KahaEtal06, KossEtal99, MarsEtal00, VargEtal97 (errata with no
registered DOI), Fred04 (article-locator record), FrieEtal99, McDoEtal10, Murd56, LeVaEtal08, PfurEtal96
(author-suffix records), Este91, Buzs02b (an unrelated candidate's suffix record), MonaAbbo11, StarDava06 and
PurcEtal10's third link (notices with no DOI found). A record that changes, or any other record of the same
DOI, has another identity and reopens the entry.
