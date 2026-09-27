# Reconciliation of resolution batches 18, 21, 22 against the final rules (2026-09-26)

Rules: resolution-plan README "Standing rules", round-1/round-2 rule answers, "Defaults chosen by Claude"
(incl. every "(default)" and "NOTE for reconciliation" line), and BRIEF.md. Browser-read pages
(Google Books, MIT Press Direct, Springer) were read in a real browser (round-2 evidence (b)).

| key | batch | change | rule | evidence URL |
|-|-|-|-|-|
| RaveEtal98 | 18 | drop -> apply: replaced by the test's original article Penrose & Raven 1936, Br J Med Psychol 16(2):97--104, @article, new key PenrRave36, DOI added, publisher/address removed | default: cited test/manual edition with no record -> original article (Wech45 precedent) | https://api.crossref.org/works/10.1111/j.2044-8341.1936.tb00690.x |
| ChenEtal15a | 18 | pages evidence DBLP -> official NeurIPS proceedings page (value unchanged 460--468) | default: NeurIPS proceedings site beats other sources | https://web.archive.org/web/20160331161552/http://papers.nips.cc/paper/5855-a-reduced-dimension-fmri-shared-response-model |
| MozeEtal09 | 18 | pages evidence DBLP -> official NeurIPS page (1321--1329 unchanged); author order kept per PDF byline | default: NeurIPS site; standing rule 3 (as printed) | https://web.archive.org/web/20150523062030/http://papers.nips.cc/paper/3731-predicting-the-optimal-spacing-of-study-a-multiscale-context-model-of-memory |
| SkagEtal93 | 18 | year 1993 -> 1992 (NIPS 5 = NIPS 1992), key SkagEtal93 -> SkagEtal92; pages evidence -> official NeurIPS page | default: conference year for proceedings; keys follow metadata | https://papers.nips.cc/paper_files/paper/1992/hash/5dd9db5e033da9c6fb5ba83c7a7ebea9-Abstract.html |
| ElliAshb88 | 18 | kept (apply) on a record of the chapter itself: Google Books full-text index of the printed book matches the chapter title on p. 33; contents '2 25 3 44'; question removed | default: reference-list-only -> drop, unless a record of the chapter itself exists | https://www.google.com/search?tbm=bks&q=%22Resource+allocation+model+of+the+effects+of+depressed+mood+states+on+memory%22 ; https://books.google.com/books?id=lAoRAQAAIAAJ |
| Swet98 | 18 | remove pages -> keep 635--702 (start 635 confirmed in the book's own text) | default: partly-confirmed chapter pages keep the cited range | https://books.google.com/books?id=1LvJ4x3QCsYC&q=%22Life+and+Death%22 |
| RaaiShif81b | 18 | remove pages -> keep 403--415 (start 403 confirmed in the book's own text) | default: partly-confirmed chapter pages | https://books.google.com/books?id=fTkQAQAAIAAJ&q=%22order+effects+in+recall%22 |
| Newm87 | 21 | remove pages -> keep 77--87 (title + 'Slater E. Newman' only on p. vii and p. 77) | default: partly-confirmed chapter pages | https://books.google.com/books?id=6S5-AAAAMAAJ&q=%22Some+effects+on+early+American+research%22 |
| Slam87 | 21 | remove pages -> keep 105--128 (title, author, affiliation on p. 105) | default: partly-confirmed chapter pages | https://books.google.com/books?id=6S5-AAAAMAAJ&q=%22Norman+J.+Slamecka%22 |
| Bron95 | 21 | remove pages -> keep 201--212 (start 201 confirmed); question removed (answered by the default) | default: partly-confirmed chapter pages | (IA evidence already in the entry notes) |
| LismEtal01 | 21 | year 2000 -> 2001, rename LismEtal00 withdrawn (key stays LismEtal01) | default: book year = imprint year as LoC records it, beats earlier Crossref/publisher print date | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&query=bath.lccn=00036768&maximumRecords=1&recordSchema=marcxml |
| Wall09 | 21 | year 2009 unchanged; evidence now the publisher's copyright line (Springer 2009); rule-level question added (LoC gives only 'c2008') | precedence: publisher/Crossref; book-year default does not cover a later Crossref date | https://link.springer.com/book/10.1007/978-1-4020-6710-5 |
| MannEtal15 | 22 | remove pages -> keep 557--566 (contents: ch. 47 at 557, ch. 48 at 567; end = next - 1) | default: partly-confirmed chapter pages + end-page rule (round 2); NOTE for reconciliation | https://books.google.com/books?vid=ISBN9780262027779&q=%22Anthony+D.+Wagner%22 |
| John02 | 22 | question removed (answered) | default: print book with later e-book reissue -> print edition, no DOI | - |
| Melt11 | 22 | question removed (answered) | default: book year = imprint year (LoC) | - |
| BrowChat95 | 22 | notes: kept 454--459 on the partly-confirmed default instead of the unevidenced "run-on" claim; rule-level question added (cited end = next start) | default: partly-confirmed chapter pages | (IA evidence already in the entry) |

Checked and left unchanged: keeps Frie79, Puff79, Tulv72 (batch 21), Tulv68, Youn68 (batch 22) all rest
on image scans / full text of the printed book (IA or Open Library search-inside), acceptable under round-2
evidence (a); post-check had no changes for them. ElliAshb89 rests on the IA scan of the Sage reprint
("Originally published as a special issue of the Journal of Social Behavior and Personality"), a record of the
work itself. Heal14 -> Heal16 keeps the DOI: the online edition (2015) precedes print (2016), so the
encyclopedia default (later online edition) does not apply; print year wins as for journals.
Keys planned in batches 18/21/22 (ChosEtal05, Kurz90, TellPalm99, LeeWang09, PenrRave36, SkagEtal92,
Mand89, Herb91, Shim95b, MannEtal14c, John99, Heal16, ZimeEtal11, CrowGree00) are free in HEAD and
unique across all 26 batch files. No title contains a dash needing `---`.
