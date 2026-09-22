# Source audit for the follow-up

This is an assistant audit, not human approval. The original 50-source blind
extraction pilot remains unchanged. The checks below concern this continuation.

## Three corrections

The source observations and before/after fields are frozen in `corrections.json`.
All three were checked against their actual author lists, titles, year, volume,
and pagination; the automated result must agree with those recorded observations.

- **GonzEtal19:** [PubMed article record](https://pubmed.ncbi.nlm.nih.gov/31461679/)
  and the [authors' NIH publication page](https://fim.nimh.nih.gov/publications/j_et_al_2019_0/)
  identify the final 2019 article. The title ends in “rest”; 116129 is the article
  locator. The six authors match in order. Adding the final DOI explicitly
  selects the journal publication while retaining its preprint relationship.
- **PeirEtal19:** the [publisher's byline](https://link.springer.com/article/10.3758/s13428-018-01193-y)
  supplies all eight names. The citation now uses the published names rather
  than extra middle initials absent from this byline. Its coordinates remain
  2019, volume 51, issue 1, pages 195–203.
- **WallEtal04:** the [original article on an author's university site](https://sites.pitt.edu/~emotion/fulltext/2004/Wallstrom_Automatic.pdf)
  names Jeffrey F. Cohn as the fourth of five authors. The correction changes
  E to F; the title, 2004 volume 53, and pages 105–119 agree.

## Dotted initials

I inspected every ordered local/source author pair in the 52-entry dry-run
output: three are the corrections above, and 49 are proposals from separating
explicitly dotted initials. This inspection concerns the author comparison;
it is not an independent reread of all 49 complete articles. Other fields still
pass the existing strict documentary checks.

Additional source spot checks covered these forms:

- **ChanEtal12b:** [PubMed](https://pubmed.ncbi.nlm.nih.gov/22480735/) lists
  Y K Chang, J D Labban, J I Gapin, J L Etnier, agreeing with the four compact
  dotted given-name strings in Crossref.
- **Newm05:** the [author's publication list](https://websites.umich.edu/~mejn/pubs.html)
  identifies the random-walk centrality article, Social Networks 27, 39–54
  (2005), by M. E. J. Newman. Crossref's `M.E. J.` is the same three initials.
- **GratEtal83:** the [author's institutional record](https://digitalcommons.usf.edu/psy_facpub/259/)
  lists Gabriele Gratton, Michael G. H. Coles, and Emanuel Donchin in order.
  This corroborates `Michael G.H` with no final period.
- **PastEtal13:** the [authors' institutional record](https://nottingham-repository.worktribe.com/output/713120/feedback-inhibition-enables-theta-nested-gamma-oscillations-and-grid-firing-fields)
  lists Hugh Pastoll, Lukas Solanka, Mark C.W. van Rossum, and Matthew F. Nolan,
  corroborating compact initials next to a full given name and a surname particle.
- **ArnoEtal80:** the [Utrecht catalogue search record](https://dbc.library.uu.nl/handle/1874/16120)
  names D.E.A.T. Arnolds, matching the four explicitly dotted initials in
  Crossref. PubMed truncates this given-name sequence to D E; no missing
  initials were inferred from that secondary record. Direct catalogue retrieval
  failed, so this corroboration is limited to its indexed record.
- **Samm69:** the [DBLP author record](https://dblp.org/pid/76/3387.html) identifies
  John W. Sammon Jr. Crossref and the citation omit the suffix. The IEEE page
  presented a robot check. `source-holds.json` preserves this unresolved
  conflict using the existing external-evidence hold, so this entry is **not**
  approved by the initials fix.

The parser does not expand undotted `AA`, infer absent middle names, equate
conflicting full names, reorder authors/initials, drop suffixes, or change
hyphenated-name handling.

## Original pilot follow-up

The remaining historical-publisher cases still need explicit imprint evidence.
An [author-hosted copy of Brett et al.](https://www.uwo.ca/bmi/owenlab/pdf/2002-Brett-NatRevNeurosci-The%20problem%20of%20functional%20localization%20in%20the%20human%20brain.pdf)
was located; author-uploaded article text also displays a 2002 Macmillan
Magazines copyright line. Copyright holder, historical publisher label, and
current registry owner are not automatically equated. No historical-publisher
alias or approval was added in this continuation.
