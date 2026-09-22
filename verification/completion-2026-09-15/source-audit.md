# Local completion source checks

This is an assistant source audit. It does not create human approvals.

The pagination pass corrected 93 entries. Every proposal contains the original
fingerprint, exact before/after page field, complete Crossref record, DOI-linked
PubMed record, and retrieval provenance. Both sources had to agree on the full
ordered author list, title, issue year, venue identity via ISSN, volume, and new
pagination. Supplied optional fields and competing-work checks remained active.
All 93 edited fingerprints then passed the production verifier. A repeat made
zero requests and wrote zero reviews.

Additional assistant checks of publisher pages covered material discrepancies:

- **MoheEtal14:** the [publisher's full issue](https://journals.sagepub.com/cms/asset/f25e6945-f10e-4d53-9fe0-7c9e113faebb/psys_25_2_full_issue.pdf)
  gives Psychological Science 25(2), 315–324, for Moher, Lakshmanan, Egeth,
  and Ewen's 2014 article. The old first page was 314.
- **RoigEtal12:** [PLOS's citation block](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0044594)
  gives 7(9), e44594 (2012), with Roig, Skriver, Lundbye-Jensen, Kiens, and
  Nielsen in that order. The old 28–32 was not its published locator.
- **Benn93:** the [publisher's article page](https://link.springer.com/article/10.3758/BF03205184)
  gives Patrick J. Bennett, Perception & Psychophysics 53, 292–304 (1993).
  The old 1759–1786 belongs to a different Bennett/Banks paper listed among
  its references. Title and DOI identify the intended 1993 work.
- **FitzEtal26:** [Nature Communications](https://www.nature.com/articles/s41467-026-69746-w)
  lists Fitzpatrick, Heusser, and Manning; volume 17, article 2055 (2026).
  The old article number 2955 was incorrect. The full title and DOI agree.

These four additional publisher checks are a spot check, not a claim that all
93 publisher PDFs were read. The two-source field comparisons cover all 93.

## Formatting fixes

The title comparator now ignores a single final sentence period, preserving
question marks, ellipses, internal punctuation, subtitles, accents, and words.
The [author's manuscript](https://psy-farrell.github.io/assets/outputs/condRecency.pdf)
and [institutional publication record](https://research-information.bris.ac.uk/en/publications/dissociating-conditional-recency-in-immediate-and-delayed-free-re/)
display Farrell's title without the final period that appears in the
[PubMed record](https://pubmed.ncbi.nlm.nih.gov/20192534/). This rule changes no
BibTeX text, and does not bypass any other bibliographic checks.

The page comparator treats identical numeric endpoints (334–334) as one page
(334), retaining leading zeroes. The [publisher's Joubert article](https://journals.sagepub.com/doi/10.2466/pms.1990.70.1.334)
and [PubMed](https://pubmed.ncbi.nlm.nih.gov/2326134/) identify page 334, volume
70(1), 1990, with the same author and DOI.

The secondary-source author comparator now uses the already-tested dotted
initial tokenization. Full-name conflicts, surname order, and suffixes still
block. The LaTeX normalization also preserves the argument of `texttt`; the
library contained one affected title, FitzMann24, which was unresolved before
the fix. Tests explicitly reject equating different monospace words.

An offline dry run produced 344 possible approvals before the monospace fix.
The final production run produced 345, including FitzMann24. All 2,350 prior
approvals retained exactly the same cached records. The repeat made zero
requests and wrote zero reviews. Ambiguous duplicate DOI registrations remained
unresolved even when their titles now match.

## Field corrections

The first dry run proposed 149 title/coordinate repairs. The final manifest has
122: 104 titles, nine volumes, five years, and four issue numbers. The rejected
27 include combined volume(issue) fields, mathematical titles, possible lost
spaces in source text, and a footnote marker. No rejected proposal was applied.
I inspected the before/after title and coordinate differences and additionally
checked these material examples against their sources:

- **BudsPric05:** [NEJM](https://www.nejm.org/doi/full/10.1056/NEJMra041071)
  lists Budson and Price, 2005, volume 352(7), 692–699. Volume 325 was wrong.
- **WangEtal15:** the [publisher's article](https://www.sciencedirect.com/science/article/pii/S0165027015001910)
  gives the title ending “An unbiased method for task-related functional
  connectivity,” Journal of Neuroscience Methods 251, 108–119 (2015).
  The [authors' manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC4500659/)
  corroborates the ordered Wang/Cohen/Li/Turk-Browne byline and that title.
- **MatsHiko09:** the [publisher's issue contents](https://www.natureasia.com/ja-jp/nature/459/7248)
  associate the article DOI with volume 459, issue 7248; the old Number 11
  represented the day of the month instead of the issue number.
- **Lism05:** [Wiley's issue contents](https://onlinelibrary.wiley.com/toc/10981063/2005/15/7)
  actually spell the title word “occuring,” agreeing with PubMed and Crossref.
  The bibliography now follows the published title rather than silently fixing
  its spelling.
- **Howa18 (excluded):** the [author manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC5881576/)
  uses “in mind.” The registry/secondary proposed join “inMind” is questionable
  source typography, so it was not copied into the bibliography.
- **MewaHinr73 (excluded):** the source title ends with an asterisk that appears
  to be a footnote marker. It remains unresolved; that marker was not copied.

All 122 revised fingerprints passed the live verifier. The repeated run made no
requests or writes. The five year changes retain their existing citation keys;
`bibcheck/key_overrides.json` exempts only their exact derived key names from
the formatter's naming rule, without suppressing any metadata checks.

## Correction-notice precedence audit

An audit of saved accepted records found 54 entries with PubMed links to
comments, preprints, or notices. Two had explicit erratum links. The selector
previously allowed a clean Crossref candidate to mask these secondary flags.
The fix blocks automatic acceptance when a validated DOI-linked PubMed record
flags an erratum, correction, retraction, or expression of concern. Ordinary
comments and preprint links are not mislabeled as corrections.

- **ChanEtal12b:** [PubMed](https://pubmed.ncbi.nlm.nih.gov/22480735/) identifies
  an erratum in Brain Research 1470, 159 (2012). The
  [author's institutional record](https://scholar.lib.ntnu.edu.tw/en/publications/erratum-the-effects-of-acute-exercise-on-cognitive-performance-a--2/)
  identifies DOI 10.1016/j.brainres.2012.06.039 for that notice.
- **MenoEtal96:** the PubMed record 8598178 identifies an erratum in volume 98(3),
  page 228 (1996). The [author's institutional record](https://pure.johnshopkins.edu/en/publications/erratum-spatio-temporal-correlations-in-human-gamma-band-electroc-3/)
  identifies DOI 10.1016/0013-4694(96)80250-1.

The notice bodies have not yet been adjudicated. These two premature approvals
must be reopened, not silently preserved. `notice-audit-results.json` records
the cache repair and proves that all other records were unchanged.


## DOI additions and explicit initials

Eighty DOI additions passed the production verifier and its zero-request,
zero-write repeat. DunlHert98 exposed Crossref's real HTTP 301 alias behavior:
10.1037//0882-7974.13.4.597 redirects to 10.1037/0882-7974.13.4.597.
The stored transport receipt follows the [documented Crossref alias mechanism](https://community.crossref.org/t/adding-redirects-for-aliased-dois-in-the-rest-api/13138).
Only a single permanent redirect between validated Crossref work endpoints is
accepted; the returned DOI must equal its target and every metadata field still
has to match. General redirects and DOI slash normalization are not allowed.

The explicit-hyphen initial fix cleared another 34 entries without bibliography
edits. It requires the same number and order of hyphen-separated name parts,
with each local part exact or an explicit single initial. It does not equate
unseparated initials with hyphenated names. The full offline run and repeat are
recorded in hyphen-results.json (2,929 verified, 3,493 unresolved at that stage).

## Author proposal audit

The post-hyphen dry run produced 193 proposals. I inspected all before/after
bylines, and held 17 for shared source errors, ambiguous family/given boundaries,
or removal of existing given-name information. The batch contains 176 proposals;
each requires full ordered byline agreement between Crossref and the DOI-linked
PubMed record, plus all other bibliographic coordinates. The frozen rejected
proposals and reasons are in author-audit-exclusions.json.

Additional documentary spot checks:

- HaxbEtal20: [eLife's own citation block](https://elifesciences.org/articles/56601/peer-reviews)
  gives James V Haxby, J Swaroop Guntupalli, Samuel A Nastase, and Ma Feilong,
  in that order; eLife 9:e56601, 2020. The proposed full byline agrees.
- BassBull06: [SAGE's article page](https://journals.sagepub.com/doi/10.1177/1073858406293182)
  identifies Danielle Smith Bassett and Ed Bullmore, 2006. This supports the
  particular published names, rather than inferring initials from other papers.
- HensEtal04: the [author-hosted published PDF](https://www.fil.ion.ucl.ac.uk/~rhenson/ni-lag.pdf),
  page 1, actually prints R.N. Henson, A. Rylands, E. Ross, P. Vuilleumeir, and
  M.D. Rugg. The proposal adds Henson's N and retains the printed Vuilleumeir
  spelling; it does not claim that this is the researcher's usual surname spelling.
- McNaShel03 (held): Crossref and PubMed both duplicate Amy Shelton. The
  [Johns Hopkins record](https://pure.johnshopkins.edu/en/publications/cognitive-maps-and-the-hippocampus-6)
  lists Timothy P. McNamara and Amy L. Shelton once each. A new proposal guard
  rejects repeated identical byline names even when both feeds repeat them.

These are additional spot checks, not a claim to have read 176 publisher PDFs.
The original representative-50 audit is a separate artifact.


## Journal proposals

Thirty-six single-field journal corrections pass the proposed two-source checks.
Unlike the normal ISSN-based venue comparison, this proposal route removes the
Crossref title from the mapped PubMed record before comparing: PubMed's native
journal title must independently agree. Historical formatter substitutions that
change that title cause the proposal to be rejected. No blanket journal alias
or date-independent successor-title mapping was introduced.

I reviewed all 36 before/after journal differences. Additional checks include:

- FortEtal02: [the authors' archived manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC4053170/)
  identifies the final article as Nature Neuroscience 5(5), 458–462 (2002), DOI
  10.1038/nn834, not Nature.
- CutlGram88: [Oxford's article record](https://academic.oup.com/geronj/article-abstract/43/3/S82/566232)
  gives Journal of Gerontology 43(3), S82–S90 (1988), Cutler and Grams.
- Mumb01: the [published article PDF](https://citeseerx.ist.psu.edu/document?doi=1850df438ed197474ba70568b23cfdc11422ae3e&repid=rep1&type=pdf)
  prints Behavioural Brain Research 127 (2001), 159–181; the proposed spelling
  retains the journal's British spelling.
- The historical Journal of Experimental Psychology entries predate its 1975
  split, documented by the [Penn Libraries serial history](https://onlinebooks.library.upenn.edu/webbin/serial?id=jexpersych).
  Their proposed journal is also independently present in each Crossref/PubMed
  pair. Modern publisher coverage pages can group predecessors under current
  titles, so the current journal label alone was not used as historical proof.


## Multiple-coordinate proposals

Twenty-four proposals repair two or three of volume, issue, and pagination.
The original title, ordered byline, year, and venue must already match the
Crossref candidate. The proposed coordinates must all pass the same full
Crossref/PubMed comparisons as the single-field corrections. An embedded
volume(issue) is split only if both embedded numbers agree with the sources.
I inspected all 24 before/after coordinate sets, including article numbers
mistaken for issue numbers and online-first placeholders.

Additional checks:

- AdamdeBe19: the [publisher page](https://journalofcognition.org/articles/10.5334/joc.70)
  explicitly gives 2019, volume 2, issue 1, page/article 33, Adam and deBettencourt.
  The proposal moves 33 from Number into Pages and sets Number to 1.
- KayEtal08: [Nature](https://www.nature.com/articles/nature06713) gives 452,
  352–355 (2008), Kay, Naselaris, Prenger, and Gallant. The
  [author's institutional record](https://experts.umn.edu/en/publications/identifying-natural-images-from-human-brain-activity/)
  additionally identifies issue 7185 and the March 20 print date. The old Number
  20 represented the day, while the old last page 356 was wrong.
- NayaSuzu11: the [publisher's digitized issue](https://www.sciencemagazinedigital.org/sciencemagazine/20110805?folio=776)
  shows the article ending on page 776 with DOI 10.1126/science.1206773 and its
  supporting-material path /333/6043/773/. [PubMed](https://pubmed.ncbi.nlm.nih.gov/21817056/)
  gives Science 333(6043), 773–776, 2011, Naya and Suzuki. The old page range was
  incorrectly stored in Number; the proposal restores the separate fields.
- KataEtal23: the publisher's DOI page returned 403 in this additional browser
  check. Its proposal is supported by the saved paired metadata, not a claim
  that the publisher PDF was inspected in this pass.


## Publisher-title pilot

The 25-entry HTML pilot initially encountered legacy HTTP DOI redirects. The
transport now upgrades only explicitly named publisher hosts directly to HTTPS,
without ever transmitting HTTP or following arbitrary hosts. Access failures
remain evidence gaps. Its improved run made 51 requests; the repeat made zero.

- Zanz19: I checked the [actual JAIR article page](https://jair.org/index.php/jair/article/view/11345).
  Its title is “Viewpoint: Human-in-the-loop Artificial Intelligence,” by Fabio
  Massimo Zanzotto, published February 10, 2019, volume 64. The page head also
  gives pages 243–252 and DOI 10.1613/jair.1.11345, consistent with Crossref. The
  correction adds the missing “Viewpoint:” prefix. The PDF returned 403 and was
  not inspected. The production check accepted this correction; repeat made no
  requests or review writes.
- HallWals02: Cambridge and Crossref both expose “10. TEACHER-STUDENT INTERACTION
  AND LANGUAGE LEARNING.” The leading number may be a chapter/heading label;
  uppercase metadata also produces poor BibTeX casing. I rejected this proposal
  pending documentary context. The new guard rejects all-uppercase multiword
  source titles and newly added numbered headings. No previously applied title
  in the 122-field batch contained either of these forms.

The next bounded collector uses Elsevier's [documented article XML endpoint](https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl),
reading only the article's direct coredata record. It saves the original XML and
its hash, validates DOI identity, rejects malformed or complex metadata, and
checks every exposed bibliographic field. This is metadata evidence, not proof
that full article text or correction-notice bodies were retrieved.

## Elsevier XML title corrections

The ten-entry pilot obtained ten metadata records and four preliminary proposals.
The wider run exhausted all 56 eligible Elsevier/Academic Press candidates, made
46 new requests, and produced 23 proposals. Its repeat made zero requests and
zero review writes. I inspected every before/after title.

McKoRatc89 remains held: both feeds would change “elaborative” to “eleborative.”
The authors' later references use “elaborative,” and the original paper still
needs inspection. The rejected proposal and reason are saved separately.
The remaining 22 proposals passed the production check with 22 requests; the
repeat made zero requests and writes. No title or author identity was inferred
from search snippets. Each changed title is corroborated by saved publisher XML
and Crossref, and the other supplied fields already matched.

Additional assistant checks included the publisher's indexed article records
for [SmitEtal71](https://www.sciencedirect.com/science/article/pii/S0022537171800646),
[Tzen73](https://www.sciencedirect.com/science/article/pii/S0022537173800234), and
[BurkEtal91](https://www.sciencedirect.com/science/article/pii/0749596X9190026G),
which confirm respectively “coding,” the complete recency title, and the final
question mark plus unhyphenated “word finding.” Their direct page requests were
not all available; the saved XML is the actual fetched publisher evidence.
Oxford's [department record](https://www.ndcn.ox.ac.uk/research/structural-physics-modeling-group/publication_modal/64896)
and the indexed published PDF first page confirm “Optimization” for JenkEtal02;
the lab's software documentation instead uses British spelling. The PDF could
not be directly fetched, so this is not a claim of visual PDF inspection.
The indexed SuriSchu99 first page also contains the missing word “model.”
[CU Boulder's author record](https://experts.colorado.edu/display/pubid_82233)
confirms BjorHeal74's title without the trailing footnote digit, its two authors,
and 13(1), 80–97 (1974).

## Combined publication fields

Two proposals retain the exact title and byline while repairing publication
fields. Each changed field separately passes the existing paired-source policy
against the full proposed citation; journal changes require PubMed's own title.

- TanrEtal08: saved Crossref and PubMed identify Journal of Neurosurgery 108(3),
  517–524 (2008), not Journal of Neurosurgery: Pediatrics. The publisher's
  registered article URL is /journals/j-neurosurg/108/3/article-p517.xml. Its
  direct browser retrieval failed; no PDF inspection is claimed.
- Colo05: both sources give 2006 and 609–623. The publisher's indexed article
  page also identifies Colom, 2006. The DOI contains 2005, which is not its
  publication year. The legacy citation key stays Colo05.

## Combined author/title and publication corrections

The broader paired-source proposal permits at most four changed fields, requires
at least three original bibliographic anchors to match, and requires either the
complete original title or complete original byline to match. It never repairs
both identity fields together. Each changed field then independently passes the
existing single-field check against the fully proposed citation.

I reviewed all 17 proposals and held CordEtal02 because its replacement byline
would remove the existing middle initial M from V M Haughton. The other 16 were
applied and verified with 16 requests; repeat made zero requests and writes.
Additional documentary checks:

- MillEtal09a: the [actual PLOS page](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1000609)
  lists Miller, Sorensen, Ojemann, and den Nijs as the four authors, with Olaf
  Sporns explicitly labeled editor. Removing Sporns from Author and supplying
  the article locator e1000609 agrees with that page.
- SerrEtal02: the [publisher record](https://www.nature.com/articles/416141a)
  identifies Nicholas G. Hatsopoulos and Matthew R. Fellows, resolving the
  misspelled Hatsopolous and incorrect M Fellous in the old bibliography. It
  also identifies Nature 416, 141–142 (2002). Direct retrieval met an anonymous
  publisher redirect; the indexed publisher record and saved paired metadata
  supplied the checked information.
- ProiEtal22: the [author institution's record](https://www.unige.ch/medecine/faculteetcite/media/decoder-le-langage-interieur-pour-soigner-les-troubles-de-la-parole)
  cites Delgado Saa as the family name and Nature Communications 13, 48 (2022).
  The two registry bylines and indexed archived published version agree.
- DawsEtal09: [PubMed](https://pubmed.ncbi.nlm.nih.gov/19796761/) explicitly
  distinguishes online publication September 30, 2009 from the final February
  2010 issue, 114(2), 207–226. The correction pairs those existing final issue
  coordinates with 2010 and adds Dawson's missing W initial. The citation key
  remains DawsEtal09.

## Unicode hyphens and exact venue variants

The comparator now recognizes U+2010 HYPHEN and U+2011 NON-BREAKING HYPHEN
as the same hyphen punctuation as ASCII. It does not remove the hyphen, merge
words, discard name parts, or allow differing full given names. An offline
preview found 30 additional exact source matches; the production reassessment
then reproduced those 30 matches without requests or bibliography edits.

Five narrowly enumerated journal names may appear with or without their leading
“The.” These names were checked against the [NLM Physiology record](https://www.ncbi.nlm.nih.gov/nlmcatalog/0266262),
[NLM Lancet Neurology record](https://www.ncbi.nlm.nih.gov/nlmcatalog/101139309),
[NLM NEJM record](https://www.ncbi.nlm.nih.gov/nlmcatalog/255562),
[IMS journal history](https://imstat.org/the-founding-of-the-ims/), and
[Oxford's Computer Journal archive](https://academic.oup.com/comjnl/issue/2/1).
The NLM punctuation variant “The Lancet. Neurology” denotes the same journal.
These are exact mappings, not a general rule that strips articles or punctuation.
In particular, Annals of Mathematical Statistics remains distinct from Annals of
Statistics, and historical journal sections and successor titles remain distinct.

### Post-Unicode paired-source corrections

Reviewed all 36 initial before/after proposals against their stored Crossref and DOI-linked PubMed records. The journal-name migration already verified DuboAlbe04 and ElgeEtal04 unchanged. Seven proposals were held in `afterunicode-audit-exclusions.json`: five discard given-name information, one imposes questionable title capitalization, and one concerns calbindin-D28k scientific notation. The remaining 27 were regenerated against current fingerprints and frozen for normal production re-verification.

Additional documentary checks: the PubMed page for [Lavie et al.](https://pubmed.ncbi.nlm.nih.gov/15355143/) puts de Fockert before Viding; the [Kane et al. record](https://pubmed.ncbi.nlm.nih.gov/15149250/) puts Hambrick before Tuholski, also corroborated by the coauthor lab publication record. The [Rickard et al. page](https://pubmed.ncbi.nlm.nih.gov/18605872/) includes fifth author M Colin Ard. The indexed [archived Haxby article](https://pmc.ncbi.nlm.nih.gov/articles/PMC40160/) and stored paired records supply the full six-person byline. Direct PMC page retrieval met a browser challenge; no claim of PDF visual inspection is made. Other repairs are the explicitly reviewed spelling, missing initials, volume, and title changes in the frozen manifest.

### Further exact journal article variants

Ten additional venue names allow an optional leading “The”, confined to journal comparison and supported by identity records below. No word corrections, generic article removal, section changes, or historical-title replacements are included. In particular, Acoustic is not Acoustical, and British Journal of Experimental Biology remains distinct from its successor.

- Acoustical Society of America: [ISSN-L 0001-4966](https://portal.issn.org/resource/ISSN-L/0001-4966), online 1520-8524.
- General Psychology: [NLM catalogue](https://www.ncbi.nlm.nih.gov/nlmcatalog/445981), ISSNs 0022-1309 / 1940-0888.
- Psychology: [publisher journal information](https://www.tandfonline.com/journals/vjrl20/about-this-journal), ISSNs 0022-3980 / 1940-1019.
- American Human Genetics: [NLM catalogue](https://www.ncbi.nlm.nih.gov/nlmcatalog/?term=0370475) and [owner](https://www.ashg.org/publications-news/the-american-journal-of-human-genetics-ajhg/), 0002-9297 / 1537-6605.
- Comparative Neurology: [NLM catalogue](https://www.ncbi.nlm.nih.gov/nlmcatalog/0406041) and [Wiley](https://onlinelibrary.wiley.com/journal/10969861), 0021-9967 / 1096-9861.
- International Robotics Research: [publisher issue masthead indexed text](https://journals.sagepub.com/cms/asset/2f35d383-9898-4a10-950b-396e57059e41/ijra_39_5.ed_board.pdf), 0278-3649 / 1741-3176.
- European Physical Journal B: [publisher journal page](https://link.springer.com/journal/10051).
- Experimental Biology: [publisher history and journal information](https://journals.biologists.com/jeb/pages/about), 0022-0949 / 1477-9145.
- British Philosophy of Science: [publisher journal information](https://www.journals.uchicago.edu/journals/bjps/advertise), 0007-0882 / 1464-3537.
- Abnormal and Social Psychology: [ISSN record](https://portal.issn.org/resource/ISSN/0096-851X), which supplies both key title and title proper.

### Author publisher pilots

The author proposal extension uses the same complete byline, duplicate-person, remaining-field, unique DOI, and known-conflict guards as the title route. The Elsevier pilot a001 received three metadata-only records without bylines, then HTTP 429 without Retry-After; no proposal or approval was made. The ten-entry ah001 HTML pilot returned nine HTTP 403 responses and one unsupported Frontiers redirect. It made 19 requests, then repeated with zero requests/writes. These are access/evidence gaps, not successful author verification.

The post-Unicode formatting check found Haxb96 would normally become HaxbEtal96 after restoring its missing authors. An exact old-key-to-expected-key exception preserves existing manuscript citations without bypassing any metadata checks.

### Publisher names with their own parenthetical acronyms

The publisher-only normalizer now recognizes eight exact full names with their own parenthetical abbreviations. It does not remove arbitrary parentheses or equate acquired companies, imprints, regional branches, or book-edition publisher strings. Bare APA remains ambiguous and is not expanded. IEEE is explicitly expanded to its documented full name; IEE and its predecessor entities remain distinct.

Primary references: [APA publishing](https://www.apa.org/pubs/about) and [APA home](https://www.apa.org/); [AAAS self-description](https://whatweknow.aaas.org/about.html); [OUP journal information](https://academic.oup.com/journals/pages/about_us/); [PLOS own organization name](https://plos.org/privacy-policy/); [ACM own publication](https://www.acm.org/binaries/content/assets/public-policy/usacm/intellectual-property/reports-and-white-papers/full_final1.pdf); [IEEE organizational history](https://europe.ieee.org/about/); [Cambridge reference publishing](https://www.cambridge.org/us/index.php/academic/reference/) and its contributor instructions; [APS publication terms](https://journals.aps.org/info/terms.html). This is a spelling/abbreviation equivalence for the same publisher, not a claim that any particular citation is verified; the full cached evidence is reassessed separately.

### PubMed suffix defect and cache audit

The post-alias batch's BellEtal91 proposal would have removed Kennedy's Jr suffix. The [current PubMed record](https://pubmed.ncbi.nlm.nih.gov/1948051/) explicitly lists D N Kennedy Jr, while Europe PMC separates firstName D N and lastName Kennedy but retains Jr only in fullName `Kennedy DN Jr`. The previous mapper ignored fullName and therefore lost this explicit source information. This proposal was held before any bibliography edit. The legacy author formatter independently discarded suffixes in valid BibTeX `family, suffix, given` forms; that was also fixed, with round-trip and key tests.

The new mapper extracts only a recognized suffix following an exact structured surname-plus-initials prefix. Conflicting suffix fields fail closed. Known suffix evidence is stored separately from entry fingerprints in `source_author_suffixes`, including an incremental history checkpoint and optional schema-2 snapshot section. It cannot disappear through a substantive entry edit, key rename, fresh registry lookup, or cache restore. Other publisher names and initials are not inferred.

The initial current-record scan found three affected approvals. The full immutable-history scan found five more and reopened eight: DonaMurd68, SwetEtal61, Murd66, Murd63c, Murd60a, Murd60b, Murd61, and DrewMurd80. No bibliography text changed during this audit. The audit retained 46 source witnesses and reached 3,310 verified / 3,112 unresolved, with zero requests and a zero-write status repeat. Earlier approvals were not silently retained after discovering the source defect.

A narrow source-combination rule can preserve the registry's complete given names while supplying an absent suffix explicitly documented by the DOI-linked PubMed byline. Ordered authors must be compatible, all other article coordinates must match, and conflicting names/suffixes remain blockers. This rule does not itself edit citations; a separate pure suffix proposal preserves all existing given names and requires normal production reassessment.

### Post-alias correction audit

Forty initial proposals were inspected. East59 remains held because the proposal discards James's full name; BellEtal91 is held for the suffix defect above. The other 38 candidates include 25 page/locator repairs, four DOI additions, three issue-number formatting repairs, five combined author/page repairs, and Nakazawa's missing final author. The [Nakazawa PubMed record](https://pubmed.ncbi.nlm.nih.gov/12040087/) and indexed published article explicitly identify Susumu Tonegawa as the eleventh author. The [APA supplemental landing page](https://supp.apa.org/psycarticles/supplemental/xge0000565/xge0000565_supp.html) gives Meyer et al.'s final pagination 1898–1913; an early author PDF still carries provisional pagination, so it was not used for final pages. These are candidate reviews, not a claim that this batch has been applied.

The eight suffix proposals were personally inspected: each adds only Jr in valid BibTeX suffix syntax and preserves all existing given names and author order. The source-labelled composite keeps every registry name part while retaining the original PubMed fullName witness. Documentary checks include [Donaldson and Murdock](https://pubmed.ncbi.nlm.nih.gov/5642138/), [Murdock's distinctiveness paper](https://pubmed.ncbi.nlm.nih.gov/14425343/), and the publisher's PsycInfo record for Swets/Tanner/Birdsall. The other five have the same explicit suffix in their saved DOI-linked MED records. No suffix was inferred from the author's identity alone or copied between publications.

### Suffix-aware follow-up corrections (September 16)

Personally compared all four `postsuffix` proposals against the complete ordered
Crossref and DOI-linked MED bylines, including raw `fullName` suffixes. ColdEtal96c
adds omitted L C Chao before R M Harper and preserves the other initials, adding
Jr to J Engel. StabEtal02a restores Richard J Staba and Jerome Engel Jr; the live
[PubMed record](https://pubmed.ncbi.nlm.nih.gov/12097521/) independently displayed
that same five-person byline. WallEtal06 uses the explicit Perrault Jr suffix
instead of placing Jr inside the surname and completes pages 11844–11849; both
sources agree on all five authors. NestCarl06 corrects Carlzon to Carlezon Jr and
restores Eric J Nestler, supported by both complete source bylines. Other supplied
fields were already supported. These are evidence-based proposals, not model
approvals. Additional live document attempts returned HTTP 403/429 or empty pages;
those unsuccessful requests supplied no new evidence.

### Frontiers retrieval and per-source full-text checkpoints

The live Frontiers DOI traversed four redirects before its current HTTPS journal
article page. The collector now allows a bounded six redirects for Frontiers only,
validating every host and retaining the chain. Other publishers retain their
existing cache entries and redirect limit. The TyngEtal17 pilot retrieved the
publisher's four-person byline, but its HTML metadata claims first page 235933,
which conflicts with the stored citation. No proposal or approval was made.
The pilot used five requests and repeated with zero requests and review writes.

Full-text caching now records individual PMC identifiers and recovers previously
queried identifiers from legacy request receipts. Newly discovered source IDs can
be checked without repeating prior successful or negative lookups. Behavioral
tests cover both earlier 200 and 404 responses and zero-write repeat runs.

### Pre-1975 Journal of Experimental Psychology titles

The [NLM catalogue record 7502586](https://www.ncbi.nlm.nih.gov/nlmcatalog/7502586)
identifies Journal of Experimental Psychology, print ISSN 0022-1015, as published
1916–1974, 103 volumes, superseded in part by four separately named journals.
[APA's title and ISSN history](https://www.apa.org/pubs/databases/psycarticles/title-history.pdf)
independently gives predecessor volumes 1–103 and successor General volumes
104 onward, starting 1975. The records were read through the web tool on September
16. These are dated distinct journals, not interchangeable normalization aliases.

Inspected the 57 journal-only registry mismatches. All supplied registry ISSNs
were 0022-1015. The conservative proposal filter yielded 35 entries after requiring
matching article metadata, the exact predecessor title/ISSN, local years within
1916–1974, volumes within 1–103, no other primary issue, unique resulting work,
and no conflicting DOI-linked secondary record. Personally reviewed all 35 keys,
dates (1927–1974), volumes (10–103), and proposed journal changes in the manifest.
Only the incorrect successor journal name changes; article titles, authors,
publication coordinates, and keys retain their existing values. Twenty-two other
journal-only cases remain held by the secondary/identity checks.

### Recognized suffix punctuation and five further bylines

Comparison now ignores a single abbreviation period only for explicit Jr, Sr,
and Roman numeral II–X suffixes. Missing/different suffixes, unknown strings,
and repeated periods remain different. Resolver 14 reassessed 3,062 unresolved
entries with no requests; none became approved without an edit, and the repeat
made zero writes. This exposed five supported author corrections. Personally
compared every ordered Crossref and MED author in `suffixperiod-proposals.json`:
GoldEtal07 restores Verne S Caviness Jr among nine complete names; RudeEtal80 and
FoxEtal86 correct the spurious third J initial of J B Ranck to the documented Jr
suffix; BunoVell77 places Jr after Buño rather than among given names and retains
the accent; StabEtal02b restores Richard J Staba and Jerome Engel Jr among its
four authors. No full names were discarded, author order and counts are unchanged,
and all five DOI-linked records agree on the byline.

The legacy journal formatter also contained mappings that replaced monograph
or Section A wording with a different journal title. Those five specific mappings
are now bypassed so formatting preserves the supplied publication identity for
verification. The spreadsheet data itself has not been rewritten.

### Suffix-only repairs corroborated by both sources

The suffix proposal route now also supports an explicit suffix supplied by both
Crossref and PubMed. It preserves every existing given name and initial, requires
compatible ordered source names and matching secondary publication coordinates,
and verifies the corrected entry normally. The earlier route for a suffix missing
from Crossref remains supported. An additional behavioral test confirms that
preserving a registry-supported full name is allowed while conflicting full names
remain blocked.

Personally compared all names in the five `suffixboth` source pairs. Dabb90 adds
Jr to James M Dabbs; JettEtal86 adds Jr to R B Freeman; MitcRanc80 adds Jr to J B
Ranck; ColdEtal96a adds Jr to J Engel; GordEtal90 adds Jr to J Hart. Raw PubMed
fullName and explicit Crossref suffix agree in each case. All existing given names,
initials, family names, author counts and order are retained.

### Ordinary PubMed commentary versus correction/version links

[NLM's linked-citation policy](https://www.nlm.nih.gov/bsd/policy/errata.html)
separately defines comments and errata: Comment in/on connects substantive
commentary to its referent article; errata covers corrections and related notices.
The [current PubMed DTD relationship enumeration](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/att-RefType-c.html)
also represents these as distinct types. The existing parser rejected any
`commentCorrectionList`, including ordinary commentary. TyngEtal17, for example,
contains a Comment in link to PMID 33147985, not an erratum link.

Resolver 15 permits only exact Comment in/on labels with identified MED numeric
PMIDs. Their complete raw links remain in source evidence. Mixed lists containing
an erratum, retraction, preprint/version, unrecognized label or malformed link
remain blocking, as do retraction flags and actual field mismatches. Both the
PubMed metadata and full-text front-matter routes share this rule. The independent
DOI-linked correction-notice index is unchanged. This change concerns bibliographic
identity, not whether a paper's scientific claims withstand criticism.

The active discovery-002 process was started with resolver 14 and finishes with
that loaded code. Run the separate `commentary` offline reassessment only after
its repeat and snapshot exports complete; do not launch overlapping cache writers.

The offline commentary preview inspected 164 unresolved entries and found 12
potential unchanged-entry matches. Personally reviewed all 12 ordered bylines,
titles, DOI links, publication coordinates, prior blockers, and relation labels.
All were Comment in links. Seven previously lacked enough registry given-name
tokens, three had conflicting registry dates resolved by the issue year, and two
had incomplete registry pagination corroborated by MED. KrakEtal01's subtitle
is represented separately in the registry and retained in the complete title
comparison. LakeEtal17 has 27 separately identified comment links, all retained.
The production run approved these same 12 entries, reaching 3,418 verified and 3,004 unresolved. Its repeat made zero requests and zero review writes.

### Discovery 002 documentary spot check

The newly found JumpEtal21 match is DOI 10.1038/s41586-021-03819-2. Personally
checked the [published Nature page](https://www.nature.com/articles/s41586-021-03819-2):
title, all 34 authors in order (including Žídek and Romera-Paredes), 2021, volume
596, and pages 583–589 agree with the existing bibliography and the newly found
registry record. Online and print dates are both in 2021. No entry edit was needed.
The batch's secondary stages, repeat, and exported counts remain the operational
acceptance check; this documentary spot check does not create a separate approval.

### PMC manuscript identifier audit

The documented PMC OAI front-matter endpoint returned KoenEtal07 metadata with
`manuscript-id` and `manuscript-id-alternative` identifiers, explicitly identifying
an NIH author manuscript. These identifiers must trigger the same version hold
as the older `manuscript` spelling. Resolver 16 adds both guards. A complete scan
of current saved JATS evidence found five affected entries (EldaEtal13,
ChanEtal10, WatrEtal13b, GhosEtal11, CoheEtal12), all already unresolved. None of
the current approvals relied on these manuscript records. Offline reassessment
preserved all 3,418 approvals; repeat made zero requests and writes.

The two-record PMC probe stopped at HTTP 429 on its second request (GuptEtal12).
That response and the successful first document are cached. Cached provider
failure is also reported as failure; no retry or alternate-endpoint bypass was
performed. The manuscript document did not create an approval.

### Post-commentary paired-source corrections

Personally compared the complete titles and every changed field in all 70
proposals against their paired Crossref and DOI-linked PubMed records, including
all ordered bylines for author changes. Held LeVaEtal10 because both feeds omit
the existing Dickson middle initial; the published byline needs adjudication.
Held GoenEtal08 because correcting its byline reveals the same work already
stored as GoenLogo08; an explicit duplicate-alias representation is needed to
preserve both citation keys. Neither held proposal is applied.

The remaining 68 proposals include 19 pagination, 25 author, six DOI additions,
five combined, five title, four issue, three journal, and one volume correction.
The [Nature article page](https://www.nature.com/articles/35066572) independently
confirms AndeGree01's venue is Nature, volume 410, pages 366–369 (2001), with
Michael C Anderson and Collin Green. Other attempted live publisher/PubMed pages
returned unavailable/empty/challenge content; these are not extra evidence.
The saved paired records, not those failed pages, support the other proposals.

The legacy formatter required a targeted fix to preserve the published
439–452.e5 pagination in GratEtal18. Regression cases preserve the electronic
suffix and reject descending, equal, zero-suffix and malformed ranges. Tulv94's
existing citation key is retained through an exact naming exception after its
six-author published byline is restored. All 68 edited entries passed production verification (67 requests, 68 review writes), reaching 3,486 verified and 2,936 unresolved. The repeat made zero requests and writes. A fresh-cache restore reproduced all 6,422 current results exactly and its repeat imported nothing.

## PMC metadata, durable notices, and issue-year corrections

The third 200-entry discovery batch completed 202 requests (200 registry searches
and two batched secondary queries) without new approvals. Its repeat made no
requests or review writes. The absence of a match is retained as unresolved.

The PMC OAI metadata route validates the OAI request and header identities,
PMCID, PMID, and DOI before passing only the identified article front matter to
the existing JATS assessor. It does not use references or nested articles to
supply fields. It retains manuscript and version annotations. HTTP/provider
failures stop the batch, and raw responses are cached with hashes. Requests are
serial, spaced at least 3.1 seconds, and this bulk backfill runs outside weekday
5 AM–9 PM US Eastern. See the [PMC OAI documentation](https://pmc.ncbi.nlm.nih.gov/tools/oai/).

The initial four-entry batch reused four successful, hash-checked probes. Its
first parser policy approved none. Inspection found historical Journal of
Neuroscience records using article-type `other` and heading `Articles`, plus
explicit initials attributes. Resolver 18 accepts this narrowly identified
publisher format only with the matching DOI prefix, journal ISSN, registry
article type, and PubMed Journal Article classification; correction/manuscript
and field-conflict guards remain. Packed names are expanded only when an exact
explicit initials attribute supports the interpretation. The second parser
policy approved these two entries, whose source titles, ordered bylines, dates,
identifiers, and coordinates I inspected:

- **OMarEtal94:** S. M. O'Mara, E. T. Rolls, A. Berthoz, R. P. Kesner;
  “Neurons responding to whole-body motion in the primate hippocampus”;
  Journal of Neuroscience 14(11), 6511–6523 (1994),
  DOI 10.1523/JNEUROSCI.14-11-06511.1994, PMID 7965055, PMC6577245.
- **KnieEtal95:** J. J. Knierim, H. S. Kudrimoti, B. L. McNaughton;
  “Place cells, head direction cells, and the learning of landmark stability”;
  Journal of Neuroscience 15(3), 1648–1659 (1995),
  DOI 10.1523/JNEUROSCI.15-03-01648.1995, PMID 7891125, PMC6578145.

**WangBuzs96** remained unresolved because its publisher front matter links a
correction, PMC6792948. This exposed a persistence gap: JATS notices needed the
same DOI-level protection already used for PubMed notices. The new incremental
JATS index recovered 11 historical notices without changing any prior approval;
the Wang record added another. Notice evidence survives bibliography edits,
key changes, and snapshot restore, including snapshots with no matching entry
fingerprints. Unrelated reference-list notices, ordinary commentary, and
manuscripts do not create this correction flag. Both complete offline guard
reassessments repeated with zero requests/writes.

The next frozen 20-PMC-record batch made 20 requests and approved **BassSuzu17**.
I inspected its identified publisher front matter and PubMed record: Julia C.
Basso and Wendy A. Suzuki, “The Effects of Acute Exercise on Mood, Cognition,
Neurophysiology, and Neurochemical Pathways: A Review,” Brain Plasticity 2(2),
127–152 (2017), DOI 10.3233/BPL-160040, PMID 29765853, PMC5928534.
The new front matter supplies the final page missing from the earlier Europe
PMC XML. Its publication date and PubMed issue year both establish 2017,
where the registry says 2016. All supplied fields pass the existing full-text
assessment. The batch repeat made zero requests and writes; all previous
approvals remained unchanged. Total: 3,494 verified, 2,928 unresolved.

Five separate issue-year corrections were inspected against complete paired
Crossref and DOI-linked PubMed records. The print issue date must be unique,
shared ISSN and complete ordered authors/title/coordinates must match, and the
normal resolver must approve the corrected result. Online dates remain in the
source evidence and cannot be chosen arbitrarily:

- **AlleEtal12b:** 2012 → 2014; Allen, Damaraju, Plis, Erhardt, Eichele,
  Calhoun, “Tracking Whole-Brain Connectivity Dynamics in the Resting State,”
  Cerebral Cortex 24(3), 663–676. DOI 10.1093/cercor/bhs352, PMID 23146964.
  The [publisher's March 2014 issue](https://academic.oup.com/cercor/issue/24/3?browseBy=volume)
  independently confirms the assignment; online publication was in 2012.
- **TigaEtal16:** 2016 → 2017; Tiganj, Jung, Kim, Howard, “Sequential
  Firing Codes for Time in Rodent Medial Prefrontal Cortex,” Cerebral Cortex
  27(12), 5663–5671. DOI 10.1093/cercor/bhw336, PMID 29145670.
- **HuanEtal01:** 2001 → 2002; Huang, Carr, Cao, “Comparing cortical
  activations for silent and overt speech using event-related fMRI,” Human
  Brain Mapping 15(1), 39–53. DOI 10.1002/hbm.1060, PMID 11747099.
  The new PMC front matter also identifies the January 2002 collection.
- **NichHolm01:** 2001 → 2002; Nichols and Holmes, “Nonparametric
  permutation tests for functional neuroimaging: A primer with examples,”
  Human Brain Mapping 15(1), 1–25. DOI 10.1002/hbm.1058, PMID 11747097.
- **MorrEtal18:** 2018 → 2019; Morres, Hatzigeorgiadis, Stathi, Comoutos,
  Arpin-Cribbie, Krommidas, Theodorakis, “Aerobic exercise for adult patients
  with major depressive disorder in mental health services: A systematic
  review and meta-analysis,” Depression and Anxiety 36(1), 39–53.
  DOI 10.1002/da.22842, PMID 30334597.

The initial issue-year production run made five registry requests but failed
closed: the runner did not pass its client to the secondary stage after entry
fingerprints changed. The incomplete result is retained in
`issueyear-initial-incomplete.json`. After fixing the handoff, one batched
PubMed query approved all five; the repeat made no requests or writes.
Keys remain unchanged, including the orphaned `AlleEtal12a` naming suffix.

For **AherBeat81**, the publisher's downloadable two-page chapter preview was
retrieved from [Springer's page-one service](https://page-one.springer.com/pdf/preview/10.1007/978-1-4684-1083-9_9).
I rendered and visually inspected page 121: the title, Sylvia Ahern/Jackson
Beatty byline, book title, and 1981 Plenum Press copyright footer agree with
those parts of the bibliography. The book's linked front-matter PDF returned
404. The preview does not supply the entire chapter or establish all imprint
fields, so this entry remains unresolved; no PDF/LLM approval was created.

## Wider PMC batch and incremental CLI acceptance

The frozen 100-record PMC batch 003 completed its source lookups without new
approvals. Its initial final consistency check stopped because **FranEtal07b**
had acquired unrelated negative evidence and a fresh audit timestamp, although
its accepted status and DOI had not changed. The newly indexed notice was for
Glimcher's DOI 10.1073/pnas.1014269108, a rejected search alternative. Frank's
accepted work is DOI 10.1073/pnas.0706111104. This was an evidence-attachment
scope bug, not a correction to the Frank article.

The cache now limits later notice attachment for a uniquely verified entry to
its accepted DOI and any explicitly supplied local DOI. A regression test proves
that an unrelated candidate's notice leaves the entire approval and audit-row
count unchanged, while a new notice for the actual accepted DOI still reopens
it. `unrelated-notice-audit-repair.json` records the single exact-result repair;
the immutable history retains the intermediate row. The batch resumed with
zero requests and writes, and its repeat also made zero requests and writes.
The saved batch result describes that cached resumption, not the initial
network collection cost. Total remains 3,494 verified / 2,928 unresolved.

The normal `verify --auto-review` command now includes the PMC metadata route.
Nine behavioral tests cover non-open-access metadata, renamed keys, substantive
edits with cached documents, 404 versus 429 checkpoints, empty selections,
portable checkpoint restore, conflicting identifiers, bulk hours, and the
actual pacing interval applied through the deferred client. The real
BassSuzu17 pre-PMC record plus its cached source was replayed through the CLI in
an isolated cache: it became verified with zero network calls, and the repeat
made no review writes. The first harness attempt failed only because its text
assertion expected uppercase “Network”; the CLI had already succeeded. The
corrected two-cycle observation is retained in `pmc-cli-results.json`.

The Wiggs original-50 publisher XML probe returned a 1998 cover date and omitted
volume/issue/pagination and byline. It therefore does not resolve the PubMed
1999 issue-year conflict. Its source response is retained in
`elsevier-year-probe.json`; no new date rule or approval was created.

## PMC batch 004 and reviewed coordinate corrections

PMC batch 004 made 98 requests for 100 frozen targets, wrote 102 review records
(including retained negative evidence), and verified two additional entries.
Its repeat made zero requests and writes. I inspected both complete identified
source records against the bibliography:

- **HolsEtal97:** Christian Hölscher, Roger Anwyl, Michael J. Rowan;
  the title concerning theta-phase stimulation, potentiation, and depotentiation
  in CA1 in vivo matches in full. Journal of Neuroscience 17(16), 6470–6477
  (1997), DOI 10.1523/JNEUROSCI.17-16-06470.1997, PMID 9236254.
  The publisher byline retains the supplied surname accent.
- **KirkMcGo14:** Neva J. Kirk-Sanchez and Ellen L. McGough, “Physical
  exercise and cognitive performance in the elderly: current perspectives,”
  Clinical Interventions in Aging 9, 51–62 (2014), DOI 10.2147/CIA.S39506,
  PMID 24379659. Publisher metadata and PubMed identify the 2014 volume,
  retaining the separate December 2013 first-publication date in evidence.

I inspected all twelve frozen PMC/PubMed coordinate proposals, including full
paired titles, complete ordered bylines, dates, journal/ISSN identity, and every
changed field. This route changes only publication coordinates; title and author
must already match both identified sources. The ordinary JATS and competing-work
checks must approve the entire proposed citation. Manuscripts, source notices,
conflicting bylines/dates/pages, and absent issue evidence still block it.

| Key | Reviewed replacement fields |
|---|---|
| HargEtal12 | Pages `73` instead of a DOI URL |
| RobiOlse19 | Volume 26, issue 7, pages 252–261 instead of DOI text in volume |
| EwbaEtal12 | Year 2013, volume 23, issue 5, pages 1073–1084 |
| KaisEtal08 | Volume 18, issue 10, pages 2286–2295 |
| EpstWard10 | Pages 294–303 instead of first page only |
| GracOnn89 | Pages 3463–3481 instead of first page only |
| CoelEtal09 | Year 2008, volume 3, issue 8, article e2862 |
| AddaEtal11 | Volume 108, issue 26, pages 10702–10707 instead of advance-publication text |
| JensMaza10 | Article 186 instead of PDF-relative pages 1–8 |
| GracBunn84 | Pages 2866–2876 instead of first page only |
| RaboEtal12 | Article 11 instead of PDF-relative pages 1–9 |
| ShinEtal08 | Volume 3, issue 1, article e1394 |

The [PLOS Coello article](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0002862)
independently confirms the six-author byline, August 6, 2008 publication and
3(8):e2862 citation. The [Cerebral Cortex May 2013 issue](https://academic.oup.com/cercor/issue/23/5)
independently places the Ewbank article at 23(5), 1073–1084. The title and author
fields are preserved in both bibliography entries; exact key exceptions retain
the original keys. All twelve staged corrections passed the legacy formatter.
The initial and reviewed proposal files preserve the three subsequently enriched
OAI sources (Hargreaves, Kaiser, Jensen) with unchanged proposed values.
All twelve passed production verification: 10 external requests and 26 review
writes, reaching 3,508 verified / 2,914 unresolved. The repeat made zero
requests and writes, and all previous approvals remained unchanged. The final
legacy bibliography formatting check also passed.

For **AherBeat81**, a newly located [ASU-hosted original book scan](https://education.asu.edu/sites/g/files/litvpz656/files/lcl/intelligencelearning.pdf)
contains eighteen scanned pages, not the complete book. I rendered and visually
inspected PDF pages 2 and 3: the title page explicitly identifies Plenum Press,
New York and London, with editors Morton P. Friedman, J. P. Das, and Neil
O'Connor; the next page gives ISBN 0-306-40643-8 and the 1981 Plenum imprint.
The scan has no extractable text. Its hash and viewed pages are recorded in
`ahern-documentary-receipts.json`, alongside the publisher's chapter preview.
The requested LOC MARC record returned HTTP 200 with an HTML “No Connections
Available” page; this is recorded as a provider failure, not catalogue evidence.
No generic Plenum/Springer alias or machine approval was introduced.

## Given-name completion and bound historical imprints

Three additional proposals preserve each supplied surname, author order, suffix,
and given-name token while adding source-documented missing names. Both complete
publisher and PubMed bylines must match the proposed result; full names cannot
shrink to initials, names cannot be dropped, and differing surnames or initials
remain held. I inspected the complete paired titles, bylines and coordinates:

- **BuraFiet09:** Yoram Burak and Ila R. Fiete; “Accurate Path Integration
  in Continuous Attractor Network Models of Grid Cells,” PLOS Computational
  Biology 5(2), e1000291 (2009), DOI 10.1371/journal.pcbi.1000291.
- **DuzeEtal01:** E. Düzel, F. Vargha-Khadem, H. J. Heinze, M. Mishkin;
  “Brain activity evidence for recognition without recollection after early
  hippocampal damage,” PNAS 98(14), 8101–8106 (2001),
  DOI 10.1073/pnas.131205798. The surname accent is preserved.
- **KranEtal09:** Cornelia Kranczioch, Simon Mathews, Phil J. A. Dean,
  Annette Sterr; “On the equivalence of executed and imagined movements:
  Evidence from lateralized motor and nonmotor potentials,” Human Brain Mapping
  30(10), 3275–3286 (2009), DOI 10.1002/hbm.20748. The publisher spells
  Dean's given names “Phil J.A.” and PubMed's firstName is “Phil J A”;
  the shorter PubMed fullName/initials summary omits the final A. The complete
  published byline is retained rather than using that shortened summary.

All three passed production verification (three requests and three reviews).
The repeat made zero requests and writes. Total: 3,511 verified / 2,911
unresolved; 782 cumulative bibliography edit operations in this continuation.
The staged legacy formatting check passed with all citation keys preserved.

A full-corpus target inventory caught a PMC integration bug not represented by
the positive pilot: unrelated research candidates can omit a DOI. The target
selector now filters source types before normalizing identifiers and safely
skips unidentified/malformed source records. Five added boundary tests cover
these cases. At this checkpoint 187 PMC targets (182 distinct records across
185 unresolved entries) remain unqueried.

The LOC retry after at least 439 seconds returned actual MARCXML for LCCN
80028692, record 4663918. Its single-date 008 field identifies 1981 and its
publication statement explicitly names Plenum Press, matching the inspected
original title page. The first failed HTML response remains recorded separately.
`bibcheck/book_editions.json` binds this reviewed original edition to the
publisher's archival book DOI and exact registry ISBN set. Resolver 19 can use
this pinned catalogue publication statement only for chapters under that book
DOI, dated 1981, whose sole registry blocker is publisher identity. Every other
citation field is compared afresh; no generic Plenum/Springer alias is added.
The rule uses catalogue metadata, with the separately inspected scans supporting
the edition binding. It never creates a human approval or accepts model output.

The initial imprint test fixture accidentally used the historical pilot entry's
`organization=Springer` field. The current entry instead has the source-reviewed
`publisher=Plenum Press`. Correcting the fixture to current content produced
22 passing imprint-boundary tests. All 730 tests and the 60-case documentary
benchmark pass. The production offline imprint reassessment verified AherBeat81, reaching
3,512 verified / 2,910 unresolved; the representative 50 now have 40 verified
and 10 unresolved entries. The run made zero requests and refreshed 2,911
unresolved review records in 97.94 seconds. Its repeat made zero requests
and writes in 24.14 seconds, with every earlier approval unchanged. Eleven
further MARC parser tests reject ambiguous dates, editions, record identity,
publication roles, and serial types even when test hashes are recomputed.
The full suite now passes 741 tests and the final legacy formatting check passed.


## September 17: remaining PMC fronts and ten corrections

PMC batch 005 collected 200 frozen entry/PMCID targets. Its first
post-collection audit stopped because FyhnEtal07, an older direct Crossref
approval without an `accepted_doi` field, acquired an unrelated Monaco 2011
correction notice from a rejected search candidate. It remained verified.
The cache now recovers the unique clean Crossref DOI for this legacy case;
ambiguous records retain all warning candidates. The repair restored only the
original approval's candidate list and timestamp, with the intervening audit
row retained. Both actual-DOI notice persistence and unrelated-DOI zero-write
reuse pass the regression. The resumed batch and repeat made zero requests
and writes; those resumption metrics do not describe the first collection's
network cost.

Four new approvals were inspected against complete publisher-front and MED
records: MarkEtal95b (Markowska, Olton, Givens; J Neurosci 15(3), 2063–2073,
1995; MED additionally labels part 1), OkunEtal07 (all nine authors, JNNP 78,
310–314, 2007), PochEtal11 (Poch, Fuentemilla, Barnes, Düzel; J Neurosci
31(19), 7038–7042, 2011), and ZikeEtal17 (all fourteen authors; PNAS 114(22),
5719–5724, 2017). Titles, names, DOI identity, journal and coordinates were
inspected; accent preservation is supported by the publisher byline.

All nine `pmccoordinates005` proposal pairs were inspected in full. They fix
KimEtal14 (PNAS 111(24), 8997–9002), YeunEtal06 (separate volume 26 / issue 5),
deGaEtal12 (2013, 23(9), 2235–2244), LianEtal12 (2013, 23(1), 80–96),
Ojem91 (2281–2287), SpieEtal13 (2015, 25(1), 10–25), JenkRang10
(30(46), 15558–15565), LiviHube87 (3416–3468), and HabeKnut09 (2010).
The three Cerebral Cortex issue assignments were independently checked on
https://academic.oup.com/cercor/issue/23/9,
https://academic.oup.com/cercor/issue/23/1, and
https://academic.oup.com/cercor/issue/25/1. The Nature article page
https://www.nature.com/articles/npp2009129 identifies volume 35, pages 4–26
(2010), separately from its online publication date. The unusually long
Livingstone/Hubel range agrees in the original JATS and MED records; direct
journal HTML returned 403. All titles and complete ordered bylines in these
source pairs agree. The existing keys remain unchanged; four exact year
naming exceptions were added.

`pmcgivennames005` contains one inspected correction: MullEtal94 adds the
source-supported initials U, S and L to Muller, Taube and Kubie respectively,
retains E Bostock and their order, and fills issue 12 / pages 7235–7251.
Crossref, publisher JATS and MED agree on the complete four-person byline.

Production verified all ten edits. Coordinates: 95.10 seconds, 10 requests,
22 review writes; repeat 71.42 seconds, zero requests/writes. Given names:
77.04 seconds, two requests, three writes; repeat 73.75 seconds, zero
requests/writes. The 3,526 verified / 2,896 unresolved baseline restored all
6,422 records exactly into a fresh cache, retaining 127 notices and 46 suffix
records; repeated import wrote zero, and SQLite integrity passed.

Cohe90's previously saved Wiley page supports its 1990 issue, but a direct
HTML-head probe returned 403. No Wiley date rule or approval was added.

## September 17 resumption: edition-level catalogue verification

The resumed LOC collection completed all 193 frozen book searches. Batch 001
previously made 10 requests; batch 002 resumed after 69 completed searches and
made 114 additional requests (369.24 seconds). Its complete repeat used cached
responses for all 183 entries, zero requests in 1.10 seconds. Full MARCXML,
query echoes, retrieval times, and hashes are retained in the source artifacts.

The production parser checks simple printed editions, complete personal bylines,
publication statements, titles/subtitles, all supplied fields, and every search
alternative. It rejects truncated searches, unparseable rivals, edited volumes,
translations, reproduced/electronic forms, ambiguous dates and publishers, and
unsupported fields. Catalogue policy 3 / resolver 22 supports multiple personal
author headings only when the transcribed byline confirms the complete ordered
list. MARC 700 alone is not evidence of authorship; its documented roles and
analytical/related-work fields are checked:
https://www.loc.gov/marc/bibliographic/bd700.html.

All 22 newly matching entries were inspected against their original fields and
complete MARC title, author, publication, year, edition and record-identity data.
They required no bibliography edits:

| Key | Checked edition and personal authors | MARC record |
|---|---|---|
| Albe00 | David Z. Albert, Time and chance, Harvard University Press, 2000 | 12064937 |
| Altm99 | Eitan Altman, Constrained Markov decision processes, Chapman & Hall/CRC, 1999 | 238369 |
| Bish06 | Christopher M. Bishop, Pattern recognition and machine learning, Springer, 2006 | 14268798 |
| Daub92 | Ingrid Daubechies, Ten lectures on wavelets, SIAM, 1992 | 2503641 |
| Este82 | William K. Estes, Models of learning, memory, and choice: selected papers, Praeger, 1982 | 4223515 |
| Horw87 | Paul Horwich, Asymmetries in time: problems in the philosophy of science, MIT Press, 1987 | 4771043 |
| Murp12 | Kevin P. Murphy, Machine learning: a probabilistic perspective, MIT Press, 2012 | 17212088 |
| Odla88 | John Odland, Spatial autocorrelation, Sage Publications, 1988 | 1004950 |
| Wick02 | Thomas D. Wickens, Elementary signal detection theory, Oxford University Press, 2002 | 12229257 |
| Ande95 | John R. Anderson, Learning and memory: an integrated approach, Wiley, 1995 | 2068246 |
| Chem09 | Anthony Chemero, Radical embodied cognitive science, MIT Press, 2009 | 15592680 |
| Clee93 | Axel Cleeremans, Mechanisms of implicit learning: connectionist models of sequence processing, MIT Press, 1993 | 2033137 |
| Edel99 | Shimon Edelman, Representation and recognition in vision, MIT Press, 1999 | 4035172 |
| Grah89 | Norma Van Surdam Graham, Visual pattern analyzers, Oxford University Press, 1989 | 4330302 |
| Hass12 | Michael E. Hasselmo, How we remember: brain mechanisms of episodic memory, MIT Press, 2012 | 16674615 |
| Kaus94 | Donald H. Kausler, Learning and memory in normal aging, Academic Press, 1994 | 2052839 |
| Newe90 | Allen Newell, Unified theories of cognition, Harvard University Press, 1990 | 4361913 |
| BraiReyn05 | Charles J. Brainerd and Valerie F. Reyna, The science of false memory, Oxford University Press, 2005 | 13610242 |
| CoheEich93 | Neal J. Cohen and Howard Eichenbaum, Memory, amnesia, and the hippocampal system, MIT Press, 1993 | 4869585 |
| GallKing09 | C. R. Gallistel and Adam Philip King, Memory and the computational brain: why cognitive science will transform neuroscience, Wiley-Blackwell, 2009 | 15486448 |
| GelmHill07 | Andrew Gelman and Jennifer Hill, Data analysis using regression and multilevel/hierarchical models, Cambridge University Press, 2007 | 14341096 |
| RogeMcCl04 | Timothy T. Rogers and James L. McClelland, Semantic cognition: a parallel distributed processing approach, MIT Press, 2004 | 13430657 |

The eight address cases use the actual first-place jurisdiction code: New York
(nyu), Massachusetts (mau), or California (cau), and the exact transcribed city.
For Anderson, the separate 2000 second edition remains a mismatching alternative;
its fields are not merged into the 1995 edition. No general city/state inference
or publisher alias was introduced.

Additional publisher checks confirmed the ISBN-bound Altman, Bishop, Daubechies,
Horwich and Murphy editions on Routledge, Springer, SIAM and MIT Press pages.
The multi-author spot checks exposed why search summaries are insufficient:
MIT paperback summaries reverse the author order for Cohen/Eichenbaum and
Rogers/McClelland, while the opened hardcover pages agree with the LOC bylines:
https://mitpress.mit.edu/9780262032032/memory-amnesia-and-the-hippocampal-system/
and https://mitpress.mit.edu/9780262182393/semantic-cognition/.
Oxford's product metadata labels Brainerd/Reyna as editors, but its reproduced
copyright-page cataloguing data and the authors' Cornell description identify
the complete authored book:
https://academic.oup.com/book/32740/chapter-abstract/272821352 and
https://hdpublications.human.cornell.edu/hdpublic/docs/The%20Science%20of%20False%20Memory%20description.pdf.
Cambridge's product page lists December 2006 sales dates while its front matter
explicitly states first publication in 2007; that distinction supports keeping
the cited edition year: https://assets.cambridge.org/97805216/86891/frontmatter/9780521686891_frontmatter.pdf.
Gallistel's institutional bibliography confirms the 2009 coauthored title and
Blackwell/Wiley imprint: https://ruccs.rutgers.edu/gallistel-publications.

Production stages: initial catalogue +9, coded addresses +8, complete author
bylines +5. Every repeat made zero requests and wrote zero reviews; every prior
approval remained identical. The 3,543/2,879 checkpoint restored all 6,422
records exactly, including 127 notices and 46 suffix records. The subsequent
3,548/2,874 baseline is exported. All 820 tests and the 60-case benchmark pass.

The Dartmouth catalog was refreshed again on September 17. The sanitized
`dartmouth-models-2026-09-17.json` records GLM-5.3 as visible, Local, and zero
input/output cost, alongside the free Flash/Gemma/Qwen alternatives. Full
GLM-5.3 remains the selected free reasoning model based on its official model
card and the prior source-extraction pilot; this is not a controlled comparison
of every available model. No model inference was needed for these catalogue
approvals, and no model output became verification evidence.

### Five inspected book-field corrections

`bookfields-proposals.json` records the complete before/after fields and direct
publisher/author sources. Rasm06 adds the omitted Christopher K. I. Williams;
the authors' original title/copyright pages identify both authors, the 2006
printed edition and ISBN 026218253X. Sear92 separates the explicitly published
initials J R. ThruEtal06 changes 2006 to the publisher's and catalogue's 2005
print-edition year. OReiMuna00 and Wass04 restore the full published subtitles.
The Springer Wasserman page distinguishes its 2004 edition/copyright from a
December 2003 sales date and later electronic releases. No edition year was
inferred from a present-day website footer.

Three unchanged queries reused catalogue evidence; the two expanded titles
required two new paced LOC searches. All five proposed complete entries passed
before editing. Staged formatting passed, all citation keys were preserved, and
exact naming exceptions were added for Rasm06 and ThruEtal06. Production:
61.99 seconds, five requests, ten review rows, all five verified. Repeat:
45.46 seconds, zero requests and writes. Total 3,553 verified / 2,869 unresolved;
797 cumulative bibliography edit operations and 28 exact key exceptions.

The Cambridge Gelman/Hill front-matter text was available in web indexing,
including its explicit first-publication statement; direct PDF retrieval timed
out after 40 seconds. No local visual-render check of that PDF is claimed.

### Corroborated article coordinates survive sparse registry deposits

Publisher-name investigation exposed a false-acceptance path: three Frontiers
records have no registry article number, while their already-saved publisher
JATS and PubMed records agree on one. Recognizing the exact Frontiers brand /
Frontiers Media SA corporate name could otherwise approve incomplete entries.
`source_locators.py` now reparses the original top-level final-article front
matter, requires the same DOI and journal ISSN, and independently matching
PubMed volume and page/article number. Missing or conflicting local coordinates
block that DOI even if another source is sparse. Manuscripts, related-version
annotations, references, ambiguous identities, and uncorroborated coordinates
cannot supply this evidence.

The new indexed evidence survives edits, key renames, and portable snapshots.
Only negative coordinate evidence transfers: later matching evidence does not
rewrite an existing approval or its timestamp. History migration retained 293
source records in 25.64 seconds and left every existing approval identical.
Boundary tests cover wrong identifiers, conflicting source coordinates,
non-final versions, stale match booleans, atomic malformed-snapshot rejection,
and zero-write reuse. The two narrowly documented corporate variants are
Frontiers / Frontiers Media SA (https://www.frontiersin.org/about/contact) and
Karger / S. Karger AG (https://karger.com/pages/catalogue-and-pricing).
Acquired publishers and historical imprints remain distinct.


Resolver 24 reassessed saved evidence without requests: 110.33 seconds,
2,869 review records; repeat 26.48 seconds, zero requests or writes. StypEtal11
and SteiRedi12 verified through the documented corporate spellings. Every
previous approval remained identical: 3,555 verified / 2,867 unresolved.

### Frontiers article numbers and PNAS publishers

I checked the original top-level JATS metadata and the full PubMed bylines and
coordinates for the following records, and compared them with the proposed
complete citations. The Frontiers publisher article pages were also inspected.
Article numbers were read from explicit `elocation-id` fields, never inferred
from DOI suffixes.

| Key | DOI | Source identity and correction |
|---|---|---|
| NewmEtal12 | 10.3389/fnbeh.2012.00024 | Newman, Gupta, Climer, Monaghan, Hasselmo; 2012; Frontiers in Behavioral Neuroscience 6:24; PMID 22707936 / PMC3374475. Added pages 24. |
| Muth13 | 10.3389/fnhum.2013.00138 | Suresh D. Muthukumaraswamy; 2013; Frontiers in Human Neuroscience 7:138; PMID 23596409 / PMC3625857. Added pages 138. |
| BarrEtal12a | 10.3389/fncir.2012.00005 | Barry, Heys, Hasselmo; 2012; Frontiers in Neural Circuits 6:5; PMID 22363266 / PMC3282552. Added pages 5. |
| KuhlEtal11 | 10.1073/pnas.1016939108 | Brice A. Kuhl, Jesse Rissman, Marvin M. Chun, Anthony D. Wagner; 2011; PNAS 108(14):5903–5908; PMID 21436044 / PMC3078372. Elsevier corrected to National Academy of Sciences. |
| GraySing89 | 10.1073/pnas.86.5.1698 | C. M. Gray and W. Singer; 1989; PNAS 86(5):1698–1702; PMID 2922407 / PMC286768. JSTOR corrected to National Academy of Sciences. |

Frontiers production verified all three (90.00 seconds, four requests, nine
review writes); repeat 78.50 seconds with zero requests/writes. The publisher
proposal generator found exactly the two PNAS cases across the remaining
library. It requires agreement between raw final publisher front matter and
Crossref on publisher, and a complete PubMed identity/coordinate match.
Conflicting publishers, other incorrect fields, manuscripts, notices, and
external review holds produce no proposal. PNAS production verified both
(82.91 seconds, two requests, two review writes); repeat 78.27 seconds with
zero requests/writes. Every previous approval stayed identical. All 6,422
citation keys are preserved; total 3,560 verified / 2,862 unresolved, with
802 cumulative bibliography edit operations. The full suite passed 856 tests
and the 60-case benchmark had zero false acceptances or missed matches.

Fresh-cache restoration reproduced all 6,422 current results exactly: 3,560
verified / 2,862 unresolved, with 127 notices, 46 suffix records, and 293
article-coordinate records retained. Reimport wrote zero records; SQLite
quick-check passed. Legacy bibliography formatting passed after these edits.


### Expanded discovery 004 and renewed pilot evidence

The frozen 500-entry batch completed in 959.18 seconds with 513 requests and
712 review rows, including 190 DOI-linked secondary lookups. None passed all
fields. Repeat took 94.40 seconds with zero requests/writes. Prior approvals
were unchanged; exported count remains 3,560 / 2,862.

The SAGE-hosted Kerby PDF was readable through web text extraction at
https://journals.sagepub.com/doi/pdf/10.2466/11.IT.3.1 . Its publisher-added
cover identifies Comprehensive Psychology 3, Article 1 (2014), Dave S. Kerby,
and DOI 10.2466/11.IT.3.1. It explicitly explains the transfer from Innovative
Teaching and directs readers to cite Comprehensive Psychology with the original
DOI. This is additional source evidence, not an automated approval: the existing
registry locator differs, and the journal-transfer notice must be retained.
Direct PDF retrieval failed first at sandbox DNS and then with publisher HTTP
403 outside the sandbox. No local PDF rendering or automated extraction match
is claimed. Cohe90's Wiley page again corroborated August 1990, volume 81,
issue 3, pages 287–297, and Gillian Cohen; this remains a source lead until
captured by the automated publication-date route.


### Post-discovery byline repair and catalogue grammar

The 500-entry discovery batch produced two correction proposals. SinkEtal98
remains held for the previously documented title-typography question.
YangEtal03's existing author field appended many cited-paper authors after the
seven actual authors. The proposed seven-person list preserves all existing
names and initials of the actual byline. I compared it with the complete
Crossref and PubMed records (PMID 12879365, DOI 10.1086/377590) and the authors'
ANU publication record, which also confirms 2003, volume 73, issue 3, pages
627–631, and the full ACTN3 title:
https://researchportalplus.anu.edu.au/en/publications/actn3-genotype-is-associated-with-human-elite-athletic-performanc/ .
The PMC page showed a browser check and the separate ANU repository returned
403; neither failed retrieval is treated as additional evidence. The correction
verified through the normal pipeline in 20.98 seconds, one request and one
review write. Repeat took 20.60 seconds with zero requests/writes. Total
3,561 verified / 2,861 unresolved and 803 bibliography edit operations.

Two further exact catalogue editions were held by parsing limitations rather
than different metadata. ClifOrd73 has the literal responsibility prefix [by]
before A. D. Cliff and J. K. Ord; MARC 001 4101364 identifies Spatial
autocorrelation, Pion, London, 1973. DeVaDeVa88 has complete inverted personal
headings and the same natural-order byline for Russell L. De Valois and Karen
K. De Valois; MARC 001 3839627 identifies Spatial vision, Oxford University
Press, New York, 1988, ISBNs 0195050193 / 9780195050196. I inspected both
complete source records and the local fields. The Oxford copyright-page search
result separately confirms first publication in 1988; its direct page retrieval
returned a cache miss, so no complete publisher-page review is claimed.

Catalogue policy 4 accepts the exact [by] prefix, groups an explicitly supplied
compound family name only when the same complete suffix appears verbatim in
the byline, and accepts a terminal spaced ISBN colon. The latter is documented
ISBD punctuation before availability terms in 020$c:
https://www.loc.gov/aba/pcc/documents/isbdmarc2016.pdf (section 3.2).
No name token is deleted or inferred. Wrong surnames, missing particles, changed
or additional given names, reordered authors, editor/translator roles, and
uncertain or extraneous ISBN text remain unresolved. All 873 tests passed.
An offline scan of all 166 unresolved books found exactly these two newly
matching editions.

Direct bounded Wiley HTML probes for Cohe90 and HamaEtal08 both returned
HTTP 403. The responses are checkpointed in `wiley-head-probe.json` and confer
no approval. The existing publisher-year adapter remains Cambridge-specific;
no unsupported Wiley rule was introduced.

Production catalogue grammar reassessment: 26.28 seconds, zero requests,
164 review writes; exactly ClifOrd73 and DeVaDeVa88 newly verified. Repeat:
25.55 seconds, zero requests/writes. Prior approvals unchanged. Exported total
3,563 verified / 2,859 unresolved; no bibliography fields changed in this pass.


### Year-refined catalogue discovery

An initial six-book literal-year probe returned only Fust05. Including the
legacy copyright prefix in the query recovered exactly one record for each of
the same six books; this was observed with real LOC responses, not assumed from
search snippets. Both probes made six requests and repeated with zero requests.
The improved query uses the cited title, author and year, never a guessed year.
A wider frozen batch covered all 62 remaining multi-record/truncated catalogue
searches: 56 new requests in 179.00 seconds, followed by 62 cache hits in 0.10
seconds with zero requests. These collectors do not grant approvals.

Policy 5 requires complete returned records and independently checks all MARC
edition metadata. No records or a still-truncated refinement cannot erase the
broader source evidence. The ordinary query remains supported in existing
snapshots; refined queries must match the current citation's exact title/author
query and explicit year. Unknown query forms, conflicting transcribed dates,
electronic editions, duplicate same-year editions, and missing byline/edition
information remain unresolved. The full suite passed 891 tests.

Offline assessment found exactly Fodo75 and Luck05 newly matching unchanged
entries. I checked complete MARC records 4106310 and 13859415 respectively:
Jerry A. Fodor, The language of thought, Crowell, New York, 1975, ISBNs
0690008023 / 9780690008029; and Steven J. Luck, An introduction to the
event-related potential technique, MIT Press, Cambridge, 2005, ISBNs
0262122774 / 0262621967 and their corresponding 13-digit forms.

`bookeditions-proposals.json` freezes three further single-field repairs:
BorgGroe05 and NoceWrig06 add edition 2, and SuttBart98 adds Barto's G initial.
I inspected full publisher bibliographic information and the corresponding
complete MARC records (13913945, 14299294, 3543602). Springer distinguishes
2005/2006 hardcovers from later paperback/electronic dates, and MIT retains the
1998 first-edition record separately from its 2018 edition. No dates or author
names were combined across editions. The revised complete entries all pass
before editing, using three cached refined queries and zero new requests.


### September 20 continuation: catalogue completion and local paper library

Discovery005 completed its 500 frozen entries: 1,285.73 seconds, 526 network
requests, 638 review writes and no immediate new approvals. The repeat took
98.20 seconds with zero requests and writes. The completed artifact was checked
after the earlier process handle had expired; the batch was not restarted.

The pending dated003 production catalogue pass approved the unchanged Fodo75
and Luck05 records inspected above: 26.17 seconds, zero requests, 61 review
writes; repeat 28.09 seconds, zero requests/writes. The three inspected
bookeditions corrections then passed complete normal verification: 53.36
seconds, three requests, six writes; repeat 48.51 seconds, zero requests/writes.
The formatter initially pruned edition fields from the staged bibliography.
Adding edition to keep_fields.txt fixed that loss, and the regression test
checks the polished book still passes the source edition comparison.

The user's Dropbox paper library was located through Dropbox's local account
configuration. A read-only inventory found 1,401 PDFs, 1,378 distinct contents.
The content-addressed first-three-page index took 46.45 seconds; 1,371 files
yielded text, 28 were textless, and two exceeded the 300,000-character bound.
A repeat hashed all files and performed zero extractions in 1.96 seconds.
Library files were not edited or copied into the repository. Paths, extracted
text and rendered previews remain in ignored .bibcheck/local-library.

There were 174 unresolved filename matches, 169 with extracted text. Searching
all bibliography titles and DOIs identified candidate mentions for 268 unresolved
entries, 207 on a first page. These counts are discovery leads only: a filename,
reference-list mention or title shared across publication versions cannot
approve an entry. No title or DOI for the ten remaining original pilot entries
was found in the indexed text; image-only files and later pages are unexamined.

I visually inspected the publisher cover and original first article page for
Box76 and Salz59. Box's cover gives George E. P. Box, Science and Statistics,
1976, Journal of the American Statistical Association 71(356):791–799, DOI
10.1080/01621459.1976.10480949. The original first page separately prints
December 1976, volume 71, number 356 and page 791. The 2012 online date and
2016 download stamp do not identify the issue year. Salzinger's cover gives
Kurt Salzinger, Experimental Manipulation of Verbal Behavior: A Review,
The Journal of General Psychology 61(1):65–94, 1959, DOI
10.1080/00221309.1959.9710241. The article's original header independently
prints the 1959 volume and full page range. Its 2010 online date and 2014
download date do not replace that year. Routledge is explicitly named on the
modern cover; this does not certify the 1959 historical imprint.

The live Dartmouth catalog still confirms zero-cost GLM 5.3, tagged Local.
Blind extraction received only cover text, without bibliography fields or the
separately recorded expected findings. Both returned every requested field
exactly after the existing literal normalization, with no differences. The
first attempt exposed an unavailable jsonschema dependency after a successful
model request; that output was not saved. The runner now uses the existing
validated pilot schema checker and checkpoints responses before validation.
The corrected two-paper run succeeded and its --offline repeat made no model
or catalog requests. These extraction findings grant no approvals.

The post-discovery scan produced twelve correction candidates. Previously
held cases remain excluded; additional proposals removing given-name detail
are recorded in postdiscovery005-audit-exclusions.json. I read the complete
Crossref and MED records for BronEtal09: DOI 10.1016/j.expneurol.2008.09.008,
PMID 18929561, all six ordered authors, full title, Experimental Neurology
215(1):20–28, January 2009. Both agree that local volume 217/pages 1–3 were
wrong. The correction verified through the normal pipeline in 21.51 seconds,
zero network requests and one review write; repeat 21.13 seconds, zero
requests/writes. A separate browser PubMed request returned a challenge; it
was not used as successful source retrieval.

The local CordEtal02.PDF exposed a publication-identity conflict: its visual
byline is D. Cordes, V. M. Haughton, K. Arfanakis, J. D. Carew, K. Maravilla,
and its footer is Proc. Intl. Soc. Mag. Reson. Med. 10 (2002). The proposed
registry repair instead describes a Magnetic Resonance Imaging journal
article, with Carew before Arfanakis and different publication coordinates.
The bibliography mixes these versions. I withheld the proposed substitution
and attached the PDF hash, visual observations and explicit conflict to its
unresolved record. The paired-source proposal generator now returns no
correction for that record. No claim was made that this local file is the
correct intended version merely because its filename matches the cite key.

Current total after these completed stages: 3,569 metadata_verified and 2,853
needs_review; 807 cumulative entry-edit operations and all original cite keys
preserved. The full test suite passes 897 tests; the documentary benchmark
passes 60/60 cases with zero false accepts or missed matches in that sample.
Full bibliography formatting and git diff --check pass.

Fresh-cache restoration then reproduced all 6,422 current records exactly at
3,569/2,853, including the attached local version conflict. Repeat imported
zero records, retained 127 notice/46 suffix/293 coordinate records, and passed
SQLite integrity checking. The original base bibliography and current
bibliography have exactly the same key set.


### September 21: source omissions versus conflicting values

The six-entry title-search experiment completed using title plus the cited
year. Box76, Bous53, FritCarl80 and PaolEtal10 returned no MED records; Salz59
and BiswEtal95 returned their existing DOI-linked records. No DOI-less identity
rule was added. The first broad title query returned malformed/truncated data.
A later FritCarl80 response also failed schema validation; a separate diagnostic
returned a valid explicit zero-hit result, so retry proceeded without relaxing
the provider validator. Completed responses are cached; repeating all six
searches made zero requests. The new collector's initial contact lookup was
fixed to use the existing configured main-cache contact rather than a fresh
empty cache. No contact data or credentials were printed.

Inspection showed that Salz59 was already linked to PMID 14441175. The record
explicitly gives July 1959, volume 61, pages 65–94, full title, Kurt Salzinger's
initial/name, and matching DOI/ISSNs, but omits issue. Crossref supplies issue 1
and its only other blocker is the 1959 print/2010 online date distinction. The
PDF cover personally checked above explicitly confirms issue 1.

Resolver 25 retains an already supported Crossref issue only for this narrow
print-year case, requiring full title/byline/year/journal/volume/pages agreement
and same DOI/overlapping ISSNs. An absent field is distinguished from empty,
null or conflicting fields. No missing MED issue is invented in its raw or
mapped record; field-level provenance identifies Crossref as the issue source.
Other original blockers, source relationships and identity conflicts remain
unresolved. The new real-record/adversarial tests include changed coordinates,
wrong DOI, author/title mismatch, notices, types, malformed issues, missing
print dates, stale match flags, current-field edits, cite-key renames, clean
snapshot restoration and a zero-write repeat. All 918 tests passed.

A full offline preflight found exactly Salz59, FeigSimo62 and WethLevi65 newly
matching (130.82 seconds). I read the complete paired records for all three.
For FeigSimo62, the Carnegie Mellon archive PDF's original page 307 visibly
prints Brit. J. Psychol. (1962), 53, 3, pp. 307–320, full title and Edward A.
Feigenbaum/Herbert A. Simon. For WethLevi65, the publisher article page explicitly
shows G. B. Wetherill/H. Levitt, full title, May 1965, volume 18 issue 1 and
pages 1–10. Source URLs and PDF hashes are in medissue-source-checks.json.
These spot checks independently support the metadata rule rather than replacing
its automated comparison with an assistant approval.

Production reassessment: 152.46 seconds, zero requests, 2,853 updated review
records; exactly those three entries newly verified. Repeat: 27.39 seconds,
zero requests/writes. Every previous approval remained identical; total
3,572 verified / 2,850 unresolved before the pending byline correction.

I also inspected the published GuimAmar05 paper hosted by the author's
Northwestern lab. The first printed page has the complete byline Roger Guimerà
and Luís A. Nunes Amaral, title, Nature 433, 24 February 2005, page 895. Its own
DOI 10.1038/nature03288 appears on its final printed page 900. The preceding
article shares page 895 and has a different DOI (nature03286), which was not
attributed to this paper. The complete registry and MED bylines agree with
the repaired names. The staged bibliography passes formatting with the exact
GuimAmar05 → GuimNune05 naming exception, preserving the original cite key.

GhosEtal11 remains held: Crossref and MED both split Abbas El Gamal into given
Abbas El / family Gamal. The author's institutional profile and research-group
identity support El Gamal as the family name; rewriting the correct braced
family name merely to satisfy that shared indexing defect was rejected.
Source: https://profiles.stanford.edu/abbas-el-gamal?tab=bio and
https://isl.stanford.edu/groups/elgamal/people.html.

The GuimAmar05 repair verified in 25.33 seconds, one network request and one
review write; repeat 22.29 seconds, zero requests/writes. Previous approvals
remained identical. Totals: 3,573 verified / 2,849 unresolved; 808 cumulative
entry-edit operations and 29 exact key exceptions (19 year, 9 author-derived,
1 orphan suffix). The full current bibliography passes formatting and the
preserved-key regression check.

The 3,573/2,849 exported baseline restored all 6,422 current records exactly
in a fresh cache. Repeat imported zero records; 127 source notices, 46 suffix
records and 293 coordinate records survived. SQLite integrity passed. All
6,422 original cite keys remain present unchanged.


### September 21: journal identity and discovery 006 source checks

NLM 9214304 explicitly lists Cognitive Brain Research as the other title of
Brain research. Cognitive brain research (ISSN 0926-6410, 1992–2005).
The exact colon/period title variants can therefore compare equal while retaining
the complete section name. Brain Research and the Reviews journal remain distinct.
I inspected both complete source bylines and publication coordinates for
ChaoKnig96, DonaRugg99, KlimEtal97b, LepaEtal00b and MeckEtal03; only the venue
variant prevented those comparisons from matching.

NLM 8908638 dates the prefixed Brain research. Brain research reviews title to
1989–2005. The formatter previously imposed this prefixed title on every input
Brain Research Reviews. It now preserves the unprefixed input. This allows the
existing strict paired-source journal proposals for EtniEtal06, KlimEtal07 and
MoraEtal07; it does not treat the historical titles as universally interchangeable.
Both feeds independently name Brain Research Reviews for these 2006/2007 papers.
Sources and method are retained in brainjournals-source-checks.json.

The discovery-006 candidate audit also found four supported corrections:
JohnRugg07 and KleeEtal13 lack volume/issue/pages; MarnEtal03 has the wrong
journal and page range; MauEtal18 has the wrong issue and omits electronic
method pages. The OUP, Neurology and Wiley article pages independently support
the first three. For MauEtal18, the Dropbox PDF is an advance copy with temporary
pages 1–10. I instead inspected the published copy hosted by the author's Boston
University lab: physical page 2 has the complete byline, DOI and page 1499;
physical page 15 ends at e4, with the footer 1499–1508.e1–e4. Registry, MED and
the author's institutional record agree on issue 10 and range 1499–1508.e4.
The local advance copy was not used as final-pagination authority. URLs and
PDF hashes are in postdiscovery006-source-checks.json.

Ten byline proposals remain held, with reasons in
postdiscovery006-audit-exclusions.json. These include lost middle initials,
replacing richer full names with initials, and questionable family-name splits
shared across sources. No such edit has been applied to increase a match count.


The first discovery-006 attempt completed all 500 title searches, then stopped
on a malformed Europe PMC response. Its failed query was not converted into
negative evidence. The resumed run reused the searches, collected 121 DOI
lookups in five requests, and reached 3,580 verified / 2,842 unresolved.
Three of the seven new matches use the Cognitive Brain Research variant rule.
Hock92, MandRitc77 and McNa92 now have explicit Crossref redirect receipts
binding duplicate DOI spellings; LachEtal00b has matching MED evidence.
I checked those four entries' full accepted source bylines and coordinates;
provenance is retained in discovery006-positive-audit.json. The resumed-run
request/time counters do not include the interrupted attempt's earlier work.

Discovery-006 completed its repeat in 101.45 seconds with zero requests and
zero review writes. The local PDF index repeat also reused all 1,401 files
with zero text extractions (3.03 seconds); its 30 existing extraction errors
remain recorded. No source-library files were modified.

Full-library offline reassessment under resolver 26 took 142.61 seconds,
made zero requests and wrote 2,349 updated unresolved decisions. Exactly
ChaoKnig96 and DonaRugg99 additionally verified, giving 3,582/2,840. The other
three Cognitive Brain Research cases were already handled inside discovery 006.
Repeat took 31.8 seconds with zero requests/writes. Prior approvals remained
identical. All 932 tests passed, with 60/60 documentary benchmark cases.

The seven frozen corrections were regenerated from the completed discovery
evidence, with identical proposed field changes. Production verification took
33.95 seconds, seven requests and seven review writes; all seven passed.
Totals reached 3,589 verified / 2,833 unresolved. The complete bibliography
passes formatting and retains all 6,422 original citation keys. Cumulative
entry-edit operations: 815; exact key exceptions remain 29.

The seven-edit repeat took 21.57 seconds with zero requests/writes. Previous
approvals remained identical and the new baseline/review queue were exported.

Clean restoration of the 3,589/2,833 checkpoint reproduced all 6,422 current
records exactly. Repeat imported zero records; 128 source notices, 46 suffix
records and 293 coordinate records survived. SQLite integrity passed.


### September 21 local OCR and documentary checks

The separate, read-only OCR pass recovered first-three-page text from all 30
ordinary extraction failures in 190.35 seconds. Repeat took 0.09 seconds with
30 cache hits and zero extractions/errors. The 39 candidate pairs cover 29
entries and grant no approvals. Cache keys bind complete PDF bytes, extraction
settings and installed tool versions. Five focused tests cover caching,
source changes, retry behavior, output isolation and false title mentions;
the full suite passes all 937 tests.

The assistant visually inspected Sper60's original first and final pages:
George Sperling, The information available in brief visual presentations,
Psychological Monographs: General and Applied 74(11):1–29 (1960). This agrees
with original-journal Crossref DOI 10.1037/h0093759 and differs in date,
container and pages from the same-title 2003 book chapter. The frozen proposal
repairs the local singular title, misspelled/incomplete journal and page 22,
and records the source-bound journal DOI. It must still pass ordinary metadata
verification after editing; OCR is not an approval route.

The Dijk59 local attachment is a retrospective EWD841/A-0 note, not the cited
journal article. Springer independently identifies the original title, E. W.
Dijkstra, Numerische Mathematik 1:269–271 (1959), and DOI 10.1007/BF01386390:
https://link.springer.com/article/10.1007/BF01386390 . The frozen DOI addition
identifies this original version separately from the 2022 book reprint.

Ande03.pdf is an unrelated Jens D. Andersen image-decomposition paper and
cannot support the Anderson citation. GoddBadd75's printed page range is
325–331, despite OCR misreading its end as 3381; title and print-year issues
still require resolution. Tulv72's OCR lacks sufficient imprint evidence.
Hashes, pages inspected and limitations are in local-ocr-audit.json. All local
paper files remain unchanged; extracted text and rendered previews remain in
ignored .bibcheck directories.

Three additional paired-source proposals from discovery 006 were separately
checked: IariEtal08 corrects Guiuseppe to Giuseppe; JerbEtal09b supplies the
complete eleven-author byline and pages 1758–1771; KiefHetr05 completes both
authors' given names and middle initials. Publisher, author-institution and
PubMed observations and access limitations are in postsecondary006-source-checks.json.
Both this three-entry stage and the two documentary edits pass complete
bibliography-formatting preflight with all 6,422 original keys retained.


Discovery 007 completed all 500 title searches and at least 24 alias probes,
then stopped on an incomplete Europe PMC HTTP-200 search response. No malformed
response was cached. The transport now retries the identical query with bounded
backoff (four attempts maximum), retaining strict hit-count/list validation and
failing closed after persistent errors. Seven additional tests cover recovered,
persistently truncated, malformed/null and legitimate empty responses. All 944
tests pass. No acceptance-policy change was introduced. The frozen batch resumed
from its cached searches; resumed counters exclude the interrupted attempt.


Discovery 007 resumed successfully: 180 secondary DOI lookups completed in nine
requests, one more than the eight batches; the exact retry cause was not logged.
The resumed
run took 117.12 seconds and wrote 180 reviews; repeat took 112.28 seconds with
zero requests and zero writes. Squi89 newly verified through Crossref's explicit
permanent double-slash DOI alias; all title, byline and coordinates were read
and agreed. Totals were 3,590 verified / 2,832 unresolved before subsequent edits.
See discovery007-positive-audit.json and discovery-007-interruption.json.

The final discovery-007 correction scan proposed five changes for four keys.
Publisher metadata independently confirms the PavlAnde05 suffix and complete
names, agreeing with raw Crossref/MED records. The full-name-plus-suffix proposal
was frozen for application. Two proposals that would remove Polyn's M or
Kahana's J were withheld. The PetrEtal95 initials-only replacement remains held
because it would discard existing full names; a repair retaining them needs a
primary page image, which was not retrievable from the publisher/PMC in this
attempt. No title-search excerpt or secondary aggregation was used as approval.


The three postsecondary006 corrections passed ordinary verification in 26.27
seconds (three requests/three reviews); repeat took 22.17 seconds with zero
requests/writes. The documentary001 Sperling and Dijkstra corrections passed in
26.47 seconds (two requests/two reviews), then repeated in 22.53 seconds with
zero requests/writes. PavlAnde05's complete names and suffix passed in 23.16
seconds (one request/one review), then repeated in 22.33 seconds with zero
requests/writes. All previous approvals stayed identical. Totals reached
3,596 verified / 2,826 unresolved; cumulative edit operations reached 821.

A new local-PDF shortlist uses both a matching filename and a first-page title
mention, then limits attention to unresolved entries with few reported issues.
These filters select leads, not approvals. Individual review found five further
source-backed repairs: Brem78's missing hyphen, CraiLock72's spurious pre-colon
space, RobbMonr51's incorrect pages, StanEtal06's journal typo, and CoheEtal16's
Willem-Park/Willem-Paul typo. Original page images were viewed for each, with
RobbMonr51's final printed page independently checked as 407. The Cohen file
is explicitly an accepted manuscript; the institution-hosted final published
PDF text independently confirms the corrected byline and final coordinates.
Two DOI additions bind the correct original journal records; Robbins/Monro's
1985 book reprint is a different version. All five staged records agree in every
field with their original-version registry records and pass full formatting.
See documentary002-source-checks.json for exact evidence and access limits.

Other leads were held: Free77's correct 35–41 page range must not be shortened
to the registry's incomplete start-page-only value; HartEtal03's printed subtitle
must not be deleted to fit a shortened registry title. Murd68's scanned byline
includes Jr and a supplement issue, requiring a complete source reconciliation
rather than a journal-only substitution. No corresponding edits were made.


All five documentary002 edits verified in 30.49 seconds, five requests and five
new review rows. Repeat took 22.88 seconds with zero requests/writes. All previous
approvals remained identical; totals reached 3,601 verified / 2,821 unresolved.
Cumulative entry-edit operations: 826; exact key exceptions remain 29. The
baseline and review queue were exported. The ordinary local index repeat reused
all 1,401 files (zero extractions, 2.9 seconds); the separate OCR repeat reused
all 30 objects (zero extractions/errors, 0.33 seconds). Candidate fingerprints
were refreshed against the edited bibliography without modifying source PDFs.

Fresh-cache restoration reproduced all 6,422 current records exactly at 3,601/2,821. Repeat imported zero; 128 notices, 48 suffix records and 293 coordinate records survived. All original keys remain and current bibliography bytes match the full-format-checked staging file. Main and restored SQLite integrity checks passed.

### September 21 discovery 008 and printed-DOI continuation

The final 167 currently eligible expanded title searches completed: 175 requests
including secondary/alias probes, 215 review writes, and one new approval
(WithMosc89). Its explicit Crossref permanent redirect joins double- and
single-slash DOI records. The complete original citation agrees with the
canonical record; no BibTeX edit was made. Repeat: zero requests and writes.
See `discovery-008-results.json` and `discovery008-positive-audit.json`.

Eight individually inspected local PDFs supplied printed publication DOIs.
Advance manuscripts were distinguished from final pagination using publisher
or PubMed records. DOI-only additions passed full formatting and ordinary
metadata verification: 3,610 verified / 2,812 unresolved. All previous approvals
remained identical; repeat used zero requests and wrote zero records. The first
network attempt was blocked by sandbox DNS; resumption completed eight live
requests in 29.54 seconds, then repeated in 21.63 seconds. Counters in
`documentary003-results.json` describe the resumed attempt. See the frozen
proposal and source-check manifests for exact per-entry observations.


### Local documentary batches 004 and 005; documented journal variants

Eight documentary004 edits passed ordinary metadata verification (32.23 seconds,
eight requests and reviews); repeat was 22.75 seconds with zero requests/writes.
Local original page images, publisher records and PubMed metadata were inspected
individually, with advance and final coordinates distinguished. The source-check
manifest records access limitations, including final text-only evidence for
ZadbEtal17 and indexed PubMed evidence for WatrEtal13a. No unavailable PDF was
claimed as visually inspected. Totals reached 3,618/2,804.

Resolver 27 recognizes three exact documented journal name variants. Its full
cached reassessment made zero requests and verified Trei98, Fris05 and Bert97;
the repeat wrote nothing. Each additional positive was independently compared
with its PubMed/PMC record (documentedjournals-positive-audit.json). Full suite:
953 passed; documentary benchmark: 60/60, no false accepts or missed matches.

Five documentary005 corrections restore source-backed author spelling/initials,
Behaviour journal spelling, printed DOIs, and BaldEtal17's final e5 pagination.
Original page images were visually inspected; Nature publisher records establish
final pagination for advance copies. Ordinary verification: 28.35 seconds, five
requests/reviews. Repeat: 23.87 seconds, zero requests/writes. Totals reached
3,626 verified / 2,796 unresolved; 847 cumulative entry-edit operations. The
withheld cases are documented separately; no author order, full name, historical
publisher, notice, or print year was discarded just to match incomplete metadata.

Dated catalogue batch 004 collected 102 searches (102 requests, then zero on
repeat). All 102 remained unresolved under complete edition assessment. Production
assessment wrote 101 reviews, made zero requests, and preserved every approval;
repeat made zero requests/writes. Fresh-cache restoration at 3,626/2,796 reproduced
all 6,422 records exactly, retained 128 notices, 48 suffix records and 293 coordinate
records, imported zero on repeat, and passed SQLite integrity checks. Current
BibTeX matches the full-format-checked documentary005 staging bytes.

### Catalogue accent discovery (policy 6)

A three-query diagnosis found that the ordinary Buzsáki search returns no records,
while the unaccented surname and printed ISBN each recover one LC edition. The
local book's title/copyright pages were visually read, with original accents and
ISBN retained. The production fallback runs only after a zero-result query and
does not relax any edition or identity comparison. Six affected books were
collected with five new requests; a separate year refinement made one request.
Both collection repeats made zero requests. Gard00's fully matching 2000 edition
was independently checked against MIT Press, including the distinct 2004 paperback.
Production review made zero requests, wrote six reviews and reached 3,627/2,795;
repeat wrote nothing. The complete suite passed 958 tests. The fresh checkpoint
restored all 6,422 records exactly, imported zero on repeat and retained all source
guards. Source audit and raw edition records are saved alongside the batch.

The local PDF index repeat reused all 1,401 file hashes with zero extractions in
3.21 seconds. Its 30 previously recorded text-extraction errors are the scanned
files handled by the separate OCR index, not new failures. A further private
shortlist contains 36 unresolved exact-filename/first-page-title leads; these are
candidates only, including four entries with unresolved source-notice relationships.

### Documentary006: complete printed article identity

BuzsEtal12's original first page restores Buzsáki's accent, Anastassiou's A,
the exact title punctuation and protected LFP capitalization; physical page 14
visually confirms the final printed page is 420, not 419. FolkEtal18's first
page supplies 38(17):4200–4211 and its publication DOI, replacing the DOI stored
in volume. GrieEtal20's first-page byline corrects Jeddi-Ayoub to Jedidi-Ayoub;
its printed footer and publisher record identify 789 as an article locator,
while PubMed/Crossref identify issue 1. All three printed final DOIs were added.
No preprint metadata was substituted for a journal version. Full bibliography
formatting passed, preserving all other entries and all 6,422 original keys.

All three then passed ordinary live verification in 23.81 seconds (three requests
and three reviews); repeat took 23.47 seconds with zero requests/writes. All prior
approvals remained identical. Totals reached 3,630 verified / 2,792 unresolved,
with 850 cumulative entry-edit operations. The original 50-entry pilot still has
40 verified and 10 explicitly unresolved entries; none was silently cleared.

Fresh-cache validation of the documentary006 export reproduced all 6,422 records
exactly at 3,630/2,792. Repeat imported zero; 128 notices, 48 suffix records and
293 coordinate records survived. Main/restored SQLite checks passed. Current
BibTeX matches the full-format-checked staging file. The local-library repeat
reused 1,401 hashes with zero extractions (2.95 seconds); originals remain read-only.

### Repository preprints: bio001, bio002 and bio003

Added a separate bioRxiv verification route bound to complete repository history,
exact-version HTML and a matching Crossref preprint record. Repository identifiers
in legacy volume/pages fields retain that role. Journal metadata never silently
replaces the cited preprint. A known withdrawal whose API title is unchanged
provides a real negative control; the history type detects the withdrawal and
notice evidence survives substantive edits and snapshot restores. That control
is confined to tests, not imported into the bibliography cache.

All eight positives were personally checked against the visible repository
title and complete byline, posting date and exact DOI/version; LeeEtal19 and
MomeHowa18 additionally match visually inspected first pages from the original
local PDFs. Their audits distinguish rendered PDF inspection from HTML reading.
The original 50-entry benchmark remains 40 verified / 10 explicitly unresolved.

The API pilot fetched four histories and two new version pages (one already
cached). The expansion fetched ten histories and seven pages; all collection
repeats made zero requests. Production bio001 added two approvals; bio002 added
five. Two apparent API author conflicts remain held: reversed order in
ZimaMann21 and a structured given/family-name split in BetzEtal19. Four unpinned
multiple-version entries also remain held.

SilvEtal19 exposed a checker error: only one side of its linked journal DOI
comparison was case-normalized. Policy 2 normalizes both sides, still rejects
different DOI identifiers and self-links, and verifies the unchanged cited
preprint. Its real-source regression test passes. The full suite passes 1,011
tests; the 60-case documentary benchmark has no false accepts or missed matches.

Bio002 production took 31.38 seconds, made zero requests and wrote ten reviews;
repeat took 29.91 seconds with zero requests/writes. Bio003 took 31.01 seconds,
made zero requests and wrote one review; repeat took 34.96 seconds with zero
requests/writes. All previous approvals remained identical. Totals reached
3,638 verified / 2,784 unresolved with 850 cumulative BibTeX edit operations.

Fresh-cache restore reproduced all 6,422 records exactly at 3,638/2,784; repeat
imported zero. All original keys and the fully formatted BibTeX staging match
were preserved. The restore retained 128 notices, 48 author-suffix records and
293 article-coordinate records; main and restored SQLite integrity checks passed.
See restore-latest.json. No cache writer remains running; no commits or pushes.

### arXiv repository route and expansion

The new route checks repository Atom, HTML head plus complete submission history,
and the DataCite DOI record. Unversioned identifiers bind to the latest version;
explicit identifiers require their selected version's own metadata. Publication
and version dates remain distinct. Raw sources, source checks and version numbers
survive snapshot export/import. Retained DOI-linked notices now also attach to
legacy repository identifiers in volume/pages before a new discovery candidate
is available.

The four-entry pilot verified PianHill22, WietKiel19 and CarlWagn18. All three
were personally checked against the visible complete byline/title/date evidence;
WietKiel19's original PDF first page was also visually inspected. AlvaEtal05's
original v2 PDF confirmed title typos but revealed a first-author name difference
from repository metadata, so an explicit source hold was attached. No citation
was edited to match the conflicting source.

Real controls demonstrate that Piantadosi-Hill v1 misspells Piantadosi as
Piantasodi, repaired in v2, and that 1805.02682 v2 is withdrawn despite its
unchanged title and available earlier v1. Neither control approves an entry or
changes bibliography spelling. Regression checks cover byline order, missing
names, year/version conflicts, malformed sources, missing histories, registry
relationships, notices, full field checks, normal CLI operation, edit invalidation,
key renames and portable restore. All 1,090 tests pass (22.03 seconds), and the
60-case documentary benchmark remains passing.

The 35-entry expansion collected 105 documents in 348.42 seconds; its repeat
made zero requests in 2.04 seconds. All 24 positive results were personally
spot-checked; BrowEtal20's original PDF confirms its complete 31-author byline,
full title and v4 stamp. The two production batches added 27 approvals without
BibTeX edits. Pilot production took 38.12 seconds (three review writes); repeat
38.61 seconds with zero requests/writes. Expansion took 44.47 seconds (35 review
writes); repeat 38.85 seconds with zero requests/writes. Neither production run
made network requests. Every prior approval remained identical.

Additional original-PDF inspection identifies ConnEtal18 as v5 dated 8 July
2018, supporting a version pin rather than an automatic first-year correction.
CerEtal18 prints Sheng-yi Kong and Mario Guajardo-Céspedes; the entire author
field needs source adjudication before a one-field change can be accepted.
The detailed checks and held cases are saved in arxiv-001/002-source-audit.json.

The 3,665 verified / 2,757 unresolved export restored all 6,422 records exactly.
Repeat import wrote zero. All original keys remain, BibTeX still matches the
full-format-checked documentary006 staging file, 128 notices/48 suffix records/
293 coordinate records survived, and main/restored SQLite integrity checks
passed. There are 28 remaining preprint leads and 28 remaining leads in the
filtered PDF shortlist. No cache writer remains running; no commits or pushes.
