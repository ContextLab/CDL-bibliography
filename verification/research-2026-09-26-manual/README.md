# Manual research, 2026-09-26: Wech45, DougPeuc73, Mann06

The user asked for these three to be resolved by manual web research, with accuracy first.
`proposals.json` has one record per entry: `{key, new_key, entrytype, fields: {field: {value, url, quote}}, remove, notes}`.
Nothing has been applied to `cdl.bib`.

| key | verdict | change |
|-|-|-|
| Wech45 | correct the entry; high confidence | title becomes "A standardized memory scale for clinical use"; add Journal = {Journal of Psychology} and Doi = {10.1080/00223980.1945.9917223}. Volume, number, pages and year are unchanged. |
| DougPeuc73 | correct as it stands; high confidence | none. Crossref and UTP list the journal under its later name, Cartographica. HathiTrust's MARC record shows "The Canadian cartographer" for v. 5-16 (1968-1979). |
| Mann06 | correct, one field added; high confidence on the facts | add Type = {Senior honors thesis} and keep @mastersthesis. Title, school, address and year are confirmed. |

Sources:

- Wech45: the Taylor & Francis page, rendered in a browser because the site returns 403 to scripts, and the Crossref record.
- DougPeuc73: the UTP article page, Crossref, and the HathiTrust catalogue record 000641805. A full-text phrase search of "The Canadian cartographer v.8-10 1971-1973" finds the title.
- Mann06: the thesis PDF (caligari.dartmouth.edu), the author's CV (contextlab.github.io), and context-lab.com/publications.

Not confirmed:

- No Brandeis catalogue or repository record was found for Mann06.
- The printed thesis carries no date. The year 2006 comes from the CV and from the PDF's creation date.
- I have not checked whether bibcheck's formatter keeps a `Type` field on @mastersthesis. Today only @techreport entries use `Type`.
