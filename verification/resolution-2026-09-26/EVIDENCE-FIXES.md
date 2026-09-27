# Evidence fixes (2026-09-26)

After the post-check read the resolution decisions, 102 wave 2-9 entries were still `needs_user`, mostly because a `set` quote covered only part of its value (validator: `postcheck.resolution_quote` = `validate.check` + `value_supported`, one URL and one contiguous quote per field; lists are not accepted). Each row below replaced the quote (usually a longer contiguous span of the same page, e.g. the whole JSTOR RIS block `EP ... SP`, the full Crossref author array, adjacent `citation_*` meta tags) or added a `set` for a field held by `quote_check_failed`. Every quote was checked with `postcheck.resolution_quote` before it was written. No value was changed except where the table says so.

Dry run (`postcheck.run(wave, write=False)` for waves 2-9, nothing written): 81 of the 102 are no longer `needs_user`; 21 remain (listed at the end).

| Batch | Key | Field | Change | Source | New quote (start) |
|-|-|-|-|-|-|
| batch-01 | CaoWors99 | author | added set | https://projecteuclid.org/journals/annals-of-applied-probability/volume-9/issue-4/The-geom | `<meta name="citation_author" content="Jin Cao" /> <meta name="citation_author" content="Keith Worsley" />` |
| batch-01 | CaoWors99 | journal | added set | https://projecteuclid.org/journals/annals-of-applied-probability/volume-9/issue-4/The-geom | `<meta name="citation_journal_title" content="The Annals of Applied Probability" />` |
| batch-01 | CaoWors99 | volume | added set | https://projecteuclid.org/journals/annals-of-applied-probability/volume-9/issue-4/The-geom | `<meta name="citation_volume" content="9" />` |
| batch-01 | CaoWors99 | number | added set | https://projecteuclid.org/journals/annals-of-applied-probability/volume-9/issue-4/The-geom | `<meta name="citation_issue" content="4" />` |
| batch-01 | CaoWors99 | year | added set | https://projecteuclid.org/journals/annals-of-applied-probability/volume-9/issue-4/The-geom | `<meta name="citation_publication_date" content="1999/11" />` |
| batch-01 | Schw78 | title | added set | https://projecteuclid.org/journals/annals-of-statistics/volume-6/issue-2/Estimating-the-Di | `<title>Estimating the Dimension of a Model</title>` |
| batch-01 | Schw78 | author | added set | https://projecteuclid.org/journals/annals-of-statistics/volume-6/issue-2/Estimating-the-Di | `<meta name="citation_author" content="Gideon Schwarz" />` |
| batch-01 | Schw78 | journal | added set | https://projecteuclid.org/journals/annals-of-statistics/volume-6/issue-2/Estimating-the-Di | `<meta name="citation_journal_title" content="The Annals of Statistics" />` |
| batch-01 | Schw78 | year | added set | https://projecteuclid.org/journals/annals-of-statistics/volume-6/issue-2/Estimating-the-Di | `<meta name="citation_publication_date" content="1978/03" />` |
| batch-01 | RendCrai00 | pages | re-quoted | http://web.archive.org/web/20220709200648/https://onlinelibrary.wiley.com/doi/abs/10.1002/ | `S43-S62.` |
| batch-02 | WangEtal13 | title | re-quoted | https://pubmed.ncbi.nlm.nih.gov/24055357/ | `TI - Voluntary exercise counteracts Abeta25-35-induced memory impairment in mice. PG - 618-25 LID - S0166-4328…` |
| batch-03 | DamiEtal99a | notes | appended |  | EVIDENCE 2026-09-26: title quote re-read in a browser (Playwright, academic.oup.com behind Cloudflare for scripts): citation_title meta prints the quoted title … |
| batch-03 | DezfDali20 | author | re-quoted | https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=31363879&rettype=me | `FAU - Parto Dezfouli, Mohsen AU - Parto Dezfouli M AD - Neuroscience & Neuroengineering Research Lab., Biomedi…` |
| batch-03 | McCuPitt43 | author | re-quoted | https://api.crossref.org/works/10.1007/bf02478259 | `vity"],"prefix":"10.1007","volume":"5","author":[{"given":"Warren S.","family":"McCulloch","sequence":"first",…` |
| batch-04 | BrigEtal18 | author | re-quoted | https://api.crossref.org/works/10.1080/02699931.2018.1478280 | `/0000-0003-0169-1360","authenticated-orcid":false,"given":"Felipe","family":"De Brigard","sequence":"first","a…` |
| batch-05 | BabiEtal08 | author | re-quoted | https://api.crossref.org/works/10.1002/hbm.20648 | `test"],"prefix":"10.1002","volume":"30","author":[{"given":"Claudio","family":"Babiloni","sequence":"first","a…` |
| batch-06 | SimoEtal04 | pages | re-quoted | https://eric.ed.gov/?id=EJ764970 | `p305-329` |
| batch-06 | EvanEtal84 | author | re-quoted | https://api.crossref.org/v1/works/10.1016/s0272-4944(84)80003-1/transform/application/vnd. | `Gary W. Evans Mary Anne Skorpanich Tommy Gärling Kendall J. Bryant Brian Bresolin` |
| batch-06 | BahrPhel87 | author | re-quoted | https://gwern.net/doc/psychology/spaced-repetition/1987-bahrick.pdf | `HARRY P. BAHRICK AND ELIZABETH PHELPS recall test, together with five alternative` |
| batch-07 | vand95 | author | re-quoted | https://pubmed.ncbi.nlm.nih.gov/8564271/ | `B A van der Kolk, R Fisler Journal of traumatic stress` |
| batch-08 | NeldWedd72 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/2344614 | `DB - JSTOR DO - 10.2307/2344614 EP - 384 IS - 3 PB - [Royal Statistical Society, Oxford University Press] PY -…` |
| batch-08 | Nobl04 | editor | re-quoted | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=3&recordSc | `edited by Bernhard Scho&#x308;lkopf, Koji Tsuda, Jean-Philippe Vert.` |
| batch-08 | Turi50 | volume | re-quoted | https://www.jstor.org/citation/ris/10.2307/2251299 | `VL - 59` |
| batch-09 | ToluEtal12 | author | re-quoted | https://www.nature.com/articles/mp201283 | `rendsLicenceType":null}},"articleInPress":"false"},"contentInfo":{"authors":["S Tolu","R Eddine","F Marti","V …` |
| batch-09 | NadeEtal00 | author | re-quoted | https://pubmed.ncbi.nlm.nih.gov/11257912/ | `labile nature of consolidation theory. K Nader, G E Schafe, J E LeDoux Nature reviews. Neuroscience Nat Rev Ne…` |
| batch-10 | KnigEtal04 | title | added set | https://portal.sahmriresearch.org/en/publications/some-normative-and-psychometric-data-for | `<meta name="citation_title" content="Some normative and psychometric data for the geriatric depression scale a…` |
| batch-10 | KnigEtal04 | journal | added set | https://portal.sahmriresearch.org/en/publications/some-normative-and-psychometric-data-for | `<meta name="citation_journal_title" content="New Zealand Journal of Psychology">` |
| batch-10 | KnigEtal04 | volume | added set | https://portal.sahmriresearch.org/en/publications/some-normative-and-psychometric-data-for | `<meta name="citation_volume" content="33">` |
| batch-10 | KnigEtal04 | number | added set | https://portal.sahmriresearch.org/en/publications/some-normative-and-psychometric-data-for | `<meta name="citation_issue" content="3">` |
| batch-10 | KnigEtal04 | year | added set | https://portal.sahmriresearch.org/en/publications/some-normative-and-psychometric-data-for | `<meta name="citation_publication_date" content="2004/11">` |
| batch-10 | ValdEtal05 | journal | re-quoted | https://pubmed.ncbi.nlm.nih.gov/16087441/ | `Melie-Garc&#xed;a, Erick Canales-Rodr&#xed;guez Philosophical transactions of the Royal Society of London. Ser…` |
| batch-10 | Sten95 | title | added set | https://api.openalex.org/works/W2145089737 | `"display_name":"The focussed D* algorithm for real-time replanning"` |
| batch-10 | Maha36 | title | added set | https://insa.nic.in/writereaddata/UpLoadedFiles/PINSA/Vol02_1936_1_Art05.pdf | `ON THE GENERALIZED DISTANCE IN STATISTICS` |
| batch-10 | Maha36 | pages | added set | https://insa.nic.in/writereaddata/UpLoadedFiles/PINSA/Vol02_1936_1_Art05.pdf | `DISTANCE IN STATISTICS. 55` |
| batch-10 | Maha36 | notes | appended |  | EVIDENCE 2026-09-26: title and end page transcribed from the INSA image-only scan (re-OCR of PDF pages 1 and 7: 'ON THE GENERALIZED DISTANCE IN STATISTICS', run… |
| batch-11 | ShapPale70 | notes | appended |  | EVIDENCE 2026-09-26: PsycNet record read in a browser (Playwright): the Citation block prints the quoted text verbatim; plain fetches get only the JavaScript sh… |
| batch-11 | BousRosn70 | title | re-quoted | https://web.archive.org/web/20230412122458/https://link.springer.com/article/10.3758/bf033 | `instruction conditions: Conditions, standard free recall instructions; Condition U, uninhibited recall instruc…` |
| batch-11 | UnswEtal09 | title | re-quoted | https://api.crossref.org/works/10.3758/pbr.16.5.931 | `000},"page":"931-937","source":"Crossref","is-referenced-by-count":69,"title":["There\u2019s more to the worki…` |
| batch-12 | EggeEtal07 | author | re-quoted | https://api.crossref.org/works/10.1016/j.neubiorev.2005.10.004 | `better"],"prefix":"10.1016","volume":"30","author":[{"given":"Laura","family":"Eggermont","sequence":"first","…` |
| batch-12 | WaszWalt83 | author | re-quoted | https://pubmed.ncbi.nlm.nih.gov/3944613/ | `iontophoresis or striatal stimulation. B L Waszczak, J R Walters The Journal of neuroscience : the official` |
| batch-13 | Denn91 | pages | re-quoted | https://www.pdcnet.org/jphil/content/jphil_1991_0088_0001_0027_0051 | `27-51</div>` |
| batch-14 | MuelEtal18 | year | added set | https://api.datacite.org/dois/text/x-bibliography/10.5281/zenodo.49907?style=apa | `Smith, J. S. (2016).` |
| batch-14 | AndrEtal74 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1421970 | `DB - JSTOR DO - 10.2307/1421970 EP - 628 IS - 4 PB - University of Illinois Press PY - 1974 SN - 00029556 SP -…` |
| batch-14 | Attn50 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1418869 | `DB - JSTOR DO - 10.2307/1418869 EP - 556 IS - 4 PB - University of Illinois Press PY - 1950 SN - 00029556 SP -…` |
| batch-14 | BousEtal54 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1418075 | `DB - JSTOR DO - 10.2307/1418075 EP - 118 IS - 1 PB - University of Illinois Press PY - 1954 SN - 00029556 SP -…` |
| batch-14 | BowmThur63 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419785 | `DB - JSTOR DO - 10.2307/1419785 EP - 445 IS - 3 PB - University of Illinois Press PY - 1963 SN - 00029556 SP -…` |
| batch-14 | Caso24 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1413823 | `DB - JSTOR DO - 10.2307/1413823 EP - 221 IS - 2 PB - University of Illinois Press PY - 1924 SN - 00029556 SP -…` |
| batch-14 | ClarEtal60 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419114 | `DB - JSTOR DO - 10.2307/1419114 EP - 40 IS - 1 PB - University of Illinois Press PY - 1960 SN - 00029556 SP - …` |
| batch-14 | Corn62 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419876 | `DB - JSTOR DO - 10.2307/1419876 EP - 491 IS - 3 PB - University of Illinois Press PY - 1962 SN - 00029556 SP -…` |
| batch-14 | Faw90 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1423212 | `DB - JSTOR DO - 10.2307/1423212 EP - 326 IS - 3 PB - University of Illinois Press PY - 1990 SN - 00029556 SP -…` |
| batch-14 | GreeCrow84 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1422530 | `DB - JSTOR DO - 10.2307/1422530 EP - 449 IS - 3 PB - University of Illinois Press PY - 1984 SN - 00029556 SP -…` |
| batch-14 | Hall54 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1418080 | `DB - JSTOR DO - 10.2307/1418080 EP - 140 IS - 1 PB - University of Illinois Press PY - 1954 SN - 00029556 SP -…` |
| batch-14 | Hash73 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1421449 | `DB - JSTOR DO - 10.2307/1421449 EP - 397 IS - 2 PB - University of Illinois Press PY - 1973 SN - 00029556 SP -…` |
| batch-15 | JenkDall24 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1414040 | `DB - JSTOR DO - 10.2307/1414040 EP - 612 IS - 4 PB - University of Illinois Press PY - 1924 SN - 00029556 SP -…` |
| batch-15 | MandEtal81 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1422742 | `DB - JSTOR DO - 10.2307/1422742 EP - 222 IS - 2 PB - University of Illinois Press PY - 1981 SN - 00029556 SP -…` |
| batch-15 | Marm83 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1422206 | `DB - JSTOR DO - 10.2307/1422206 EP - 35 IS - 1 PB - University of Illinois Press PY - 1983 SN - 00029556 SP - …` |
| batch-15 | MarmEtal78 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1421694 | `DB - JSTOR DO - 10.2307/1421694 EP - 490 IS - 3 PB - University of Illinois Press PY - 1978 SN - 00029556 SP -…` |
| batch-15 | MeltIrwi40 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1417415 | `DB - JSTOR DO - 10.2307/1417415 EP - 203 IS - 2 PB - University of Illinois Press PY - 1940 SN - 00029556 SP -…` |
| batch-15 | MeltvonL41 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1416789 | `DB - JSTOR DO - 10.2307/1416789 EP - 173 IS - 2 PB - University of Illinois Press PY - 1941 SN - 00029556 SP -…` |
| batch-15 | NairEtal95 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1422894 | `DB - JSTOR DO - 10.2307/1422894 EP - 358 IS - 3 PB - University of Illinois Press PY - 1995 SN - 00029556 SP -…` |
| batch-15 | NewmBuck62 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419866 | `DB - JSTOR DO - 10.2307/1419866 EP - 436 IS - 3 PB - University of Illinois Press PY - 1962 SN - 00029556 SP -…` |
| batch-15 | Ober28 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1414490 | `DB - JSTOR DO - 10.2307/1414490 EP - 302 IS - 2 PB - University of Illinois Press PY - 1928 SN - 00029556 SP -…` |
| batch-15 | PollGero68 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1420627 | `DB - JSTOR DO - 10.2307/1420627 EP - 313 IS - 3 PB - University of Illinois Press PY - 1968 SN - 00029556 SP -…` |
| batch-15 | Post62 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419861 | `DB - JSTOR DO - 10.2307/1419861 EP - 389 IS - 3 PB - University of Illinois Press PY - 1962 SN - 00029556 SP -…` |
| batch-15 | Robi27 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1415419 | `DB - JSTOR DO - 10.2307/1415419 EP - 312 IS - 1/4 PB - University of Illinois Press PY - 1927 SN - 00029556 SP…` |
| batch-15 | Rock57 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419320 | `DB - JSTOR DO - 10.2307/1419320 EP - 193 IS - 2 PB - University of Illinois Press PY - 1957 SN - 00029556 SP -…` |
| batch-15 | RockHeim59 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1420207 | `DB - JSTOR DO - 10.2307/1420207 EP - 16 IS - 1 PB - University of Illinois Press PY -` |
| batch-15 | SpecBied76 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1421465 | `DB - JSTOR DO - 10.2307/1421465 EP - 679 IS - 4 PB - University of Illinois Press PY - 1976 SN - 00029556 SP -…` |
| batch-15 | UndeEtal62 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419860 | `DB - JSTOR DO - 10.2307/1419860 EP - 371 IS - 3 PB - University of Illinois Press PY - 1962 SN - 00029556 SP -…` |
| batch-15 | ViniNels79 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1421923 | `DB - JSTOR DO - 10.2307/1421923 EP - 276 IS - 2 PB - University of Illinois Press PY - 1979 SN - 00029556 SP -…` |
| batch-15 | WatkEtal89 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1422957 | `DB - JSTOR DO - 10.2307/1422957 EP - 270 IS - 2 PB - University of Illinois Press PY - 1989 SN - 00029556 SP -…` |
| batch-15 | Waug62 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1419602 | `DB - JSTOR DO - 10.2307/1419602 EP - 192 IS - 2 PB - University of Illinois Press PY - 1962 SN - 00029556 SP -…` |
| batch-15 | WelcBurn24 | pages | re-quoted | https://www.jstor.org/citation/ris/10.2307/1414018 | `DB - JSTOR DO - 10.2307/1414018 EP - 401 IS - 3 PB - University of Illinois Press PY - 1924 SN - 00029556 SP -…` |
| batch-16 | CaliVita05 | author | re-quoted | https://api.crossref.org/works/10.1109/tkde.2007.48 | `tance"],"prefix":"10.1109","volume":"19","author":[{"given":"Rudi L.","family":"Cilibrasi","sequence":"first",…` |
| batch-16 | LiEtal24b | withdraw | ['doi', 'volume'] -> [] (the withdraw popped its own `set` doi/volume) |  |  |
| batch-17 | VodrEtal16 | author | re-quoted | https://api.crossref.org/works/10.1016/j.neuroimage.2017.06.042 | `ations"],"prefix":"10.1016","volume":"180","author":[{"given":"Kiran","family":"Vodrahalli","sequence":"first"…` |
| batch-17 | PresEtal93 | title | re-quoted | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSc | `Numerical recipes in C the art of scientific computing` |
| batch-18 | TellPalm98 | year | re-quoted | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&query=bath.lccn=99011115& | `<subfield code="b">MIT Press,</subfield> <subfield code="c">c1999.</subfield>` |
| batch-18 | RaveEtal98 | author | re-quoted | https://api.crossref.org/works/10.1111/j.2044-8341.1936.tb00690.x | `ICATION"],"prefix":"10.1111","volume":"16","author":[{"given":"L. S.","family":"PENROSE","sequence":"first","a…` |
| batch-18 | ConwEtal07 | year | re-quoted | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&query=bath.lccn=200600985 | `<subfield code="b">Oxford University Press,</subfield> <subfield code="c">2007.</subfield>` |
| batch-18 | ConwEtal07 | editor | re-quoted | https://api.crossref.org/works/10.1093/acprof:oso/9780195168648.001.0001 | `mic.oup.com\/book\/25561"}},"subtitle":[],"editor":[{"given":"Andrew","family":"Conway","sequence":"first","af…` |
| batch-18 | LeeWang08 | title | re-quoted | https://www.cns.nyu.edu/wanglab/publications/pdf/neuroeconomics_chap.pdf | `31 Mechanisms for Stochastic Decision Making in the Primate Frontal Cortex: Single-neuron Recording and Circui…` |
| batch-18 | ChenEtal15a | pages | re-quoted | https://web.archive.org/web/20160331161552/http://papers.nips.cc/paper/5855-a-reduced-dime | `in Neural Information Processing Systems 460 468 http://papers.nips.cc/paper/5855-a-reduced-dimension-fmri-sha…` |
| batch-18 | MozeEtal09 | pages | re-quoted | https://web.archive.org/web/20150523062030/http://papers.nips.cc/paper/3731-predicting-the | `in Neural Information Processing Systems 1321 1329 http://papers.nips.cc/paper/3731-predicting-the-optimal-spa…` |
| batch-18 | SkagEtal93 | pages | re-quoted | https://web.archive.org/web/20160411054441/http://papers.nips.cc/paper/671-an-information- | `in Neural Information Processing Systems 1030 1037 http://papers.nips.cc/paper/671-an-information-theoretic-ap…` |
| batch-19 | AtkiJuol74 | author | re-quoted | https://escholarship.org/content/qt40x8f9s7/qt40x8f9s7.pdf | `Authors Atkinson, Richard C. Juola, James F.` |
| batch-20 | Murd89 | author | re-quoted | https://archive.org/services/search/beta/page_production/?service_backend=fts&hits_per_pag | `Distributed Memory Model}}}\nBennet B. Murdock","for the past 10 years. \u201c{{{Learning` |
| batch-20 | Luce59 | pages | re-quoted | https://api.openalex.org/works/W3036946786 | `"biblio":{"volume":"1","issue":null,"first_page":"103","last_page":"189"}` |
| batch-21 | Herb34 | pages | added set | https://archive.org/download/johannfriedrichh04unse_0/page/n403.jpg | `376 II. Lehrbuch zur Psychologie.` |
| batch-21 | Herb34 | notes | appended |  | EVIDENCE 2026-09-26: p. 376 folio transcribed from the scan page image (archive.org page n403, header '376 II. Lehrbuch zur Psychologie.'), which the djvu OCR m… |
| batch-23 | Gold87 | author | re-quoted | https://pubmed.ncbi.nlm.nih.gov/3318747/ | `cortex and its relevance to dementia. P S Goldman-Rakic Archives of gerontology and geriatrics Arch` |
| batch-23 | SnijBosk12 | booktitle | re-quoted | http://lx2.loc.gov:210/LCDB?operation=searchRetrieve&version=1.1&maximumRecords=1&recordSc | `Snijders, T. A. B. Multilevel analysis : an introduction to basic and advanced multilevel modeling / Tom A.B. …` |
| batch-23 | AdamEtal10 | title | re-quoted | https://www.osti.gov/servlets/purl/991842 | `Release Printed Updated May 7, 2010 DAKOTA, A Multilevel Parallel Object-Oriented Framework for Design Optimiz…` |
| batch-23 | Baas05 | title | added set | https://pypi.org/pypi/PyODE/json | `Modules"],"description":"PyODE\r\n=====\r\n\r\nPyODE is a set of open-source Python bindings for The Open Dyna…` |
| batch-24 | TorvHama05 | author | re-quoted | https://api.github.com/repos/git/git/commits/e83c5163316f89bfbde7d9ab23ca2e25604af290 | `MTZmODliZmJkZTdkOWFiMjNjYTJlMjU2MDRhZjI5MA==","commit":{"author":{"name":"Linus Torvalds","email":"torvalds@pp…` |
| batch-24 | vond81 | editor | re-quoted | https://api.crossref.org/works/10.1007/978-1-4612-4320-5 | `0.1007\/978-1-4612-4320-5"}},"subtitle":[],"editor":[{"given":"Eytan","family":"Domany","sequence":"first","af…` |
| batch-25 | BernClif94 | author | re-quoted | https://api.openalex.org/works/W116902681 | `74"]}],"countries":["US"],"is_corresponding":false,"raw_author_name":"Donald J. Berndt","raw_affiliation_strin…` |
| batch-25 | RagaWill18 | author | re-quoted | https://api.crossref.org/works/10.25080/Majora-4af1f417-011 | `scale"],"prefix":"10.25080","author":[{"given":"Project","family":"Jupyter","sequence":"first","affiliation":[…` |
| batch-13 | Denn91 | pages | re-quoted | pdcnet.org | `<div>Pages 27-51</div>` |
| batch-11 | KahaEtal08c | (new row) | apply: title, pages 1119--1125, doi 10.1037/a0013724 from Crossref; follows the rename to HEAD KahaEtal08b | api.crossref.org/works/10.1037/a0013724 | see row |

## Notes on particular fixes

- Browser reads (lenient rule): DamiEtal99a (OUP citation_title, Cloudflare blocks scripts) and ShapPale70 (PsycNet Citation block, JavaScript only) were read in a Playwright browser on 2026-09-26 and match the existing quotes verbatim; the notes now say so.
- Scan transcriptions (lenient rule): Maha36 title and end page re-OCR'd from the INSA image-only PDF (pages 1 and 7); Herb34 p. 376 folio read from archive.org page image n403 (the djvu OCR misread it).
- Author names from other records of the same author (author-name rule): WaszWalt83 (PubMed 3944613, Waszczak & Walters 1986), NadeEtal00 (PubMed 11257912, Nader, Schafe & LeDoux 2000), Gold87 (PubMed 3318747, ASCII-hyphen 'Goldman-Rakic'; Crossref prints U+2010 which the validator does not fold).
- WangEtal13: the validator cannot read Greek beta; the quote is the MEDLINE record from the TI line ('Abeta25-35') through RN '0 (Amyloid beta-Peptides)'.
- ValdEtal05: journal quote from PubMed 16087441 (NLM title 'Philosophical transactions of the Royal Society of London. Series B, Biological sciences').
- Index records used where no publisher text is fetchable: Sten95 title (OpenAlex; IJCAI TOC misprints 'Replannig'), Luce59 pages (OpenAlex biblio 103-189; the earlier IA search hit no longer returns the snippet), Baas05 title (PyPI project description).
- MuelEtal18: added `year` 2016 (DataCite v1.2.1 citation) so the key MuelEtal16 follows the corrected metadata.
- LiEtal24b: removed `withdraw: [doi, volume]`, which cancelled the row's own `set` values.

## Still needs_user after the dry run (21)

- Inferred end pages (next start - 1, user rule) that no source prints, so no quote can contain them; the validator has no next-start rule: Half88, TellPalm98, Shal75, Lovr80, Murd89, Murd99, OhrtGron99, Jord86, Bjor89, BenaEtal04, CraiRabi84 (also title split across two IA snippets and roman 'X' not after 'vol').
- End page printed only far from the start page (one quote cannot span them): KahaEtal08a (folios 467 and 490 about 150k characters apart; Crossref 1-24), Rans02 (39 in contents, 86 as running head), MullSchu94 (two-part 81--190, 257--339).
- Gomu53: 1--94 comes from the catalogue extent '94 p.'; no record prints page 1 (monograph-extent rule question still open).
- HallGree08: volume 1 comes from Crossref's 'I-212' page prefix (default rule); the validator reads roman numerals only after 'vol'.
- McCaEtal06: pages 12--14 only as PDF folios on three separate pages; DOI held because the Crossref API returns 404 for 10.1609/aimag.v27i4.1904 (post-check needs the registry title).
- VodrEtal16 (pages), JainHuth18 (volume), GoldEtal21 (pages), TsitEtal19 (volume): HEAD's field holds a junk URL/DOI; the researcher's or reviewer's removal of that field runs after the resolution and drops the resolution's `set` (postcheck.py, researcher/reviewer removal blocks exempt only reviewer-sourced values). Needs a post-check change; not fixable in the batch files.
