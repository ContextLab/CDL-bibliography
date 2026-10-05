# cdlbib

`cdlbib` is a command-line tool that checks the formatting of the
[CDL bibliography](https://github.com/ContextLab/CDL-bibliography) (a BibTeX file,
`cdl.bib`) and verifies each entry's citation against published records.

If you are a member of the Contextual Dynamics Laboratory at Dartmouth College, we use this package to manage a single bibliography "database" (bibtex file) to ensure accuracy and consistency across all of our written documents.

If you are *not* a CDL member, you probably won't want to use this package directly. However, you may find it useful to adapt the approach for your own research group; feel free to use, modify, adapt, etc., as you wish!

## What it does

- Checks that every entry in `cdl.bib` follows the bibliography's formatting rules.
- Verifies each entry's citation against published records (Crossref, Europe PMC,
  publisher pages, library catalogues, preprint servers and others).
- Records a human review of an entry under the reviewer's GitHub login.
- Sends a change to the bibliography as a pull request from your own fork.
- Optionally reads PDFs to collect quoted evidence for an entry (the `research` extra).
- Links the bibliography into your TeX tree (`cdlbib setup`) and exports the entries a
  paper cites as a `.bib` or a compiled `.bbl` (`cdlbib export`).
- Offers these tasks in a local web interface in your browser (`cdlbib web`), except the
  compiled `.bbl`, which only `cdlbib export --bbl` makes.

## Requirements

Python 3.11 or later. The [GitHub CLI](https://cli.github.com) (`gh`) is needed for
recording reviews and for sending changes.

## Install

```bash
python -m pip install cdlbib
```

The tool downloads the bibliography on first use and checks for updates when commands
run. See the [README](https://github.com/ContextLab/CDL-bibliography/blob/master/README.md#installation)
for library locations and usage.

## Documentation

- Repository: <https://github.com/ContextLab/CDL-bibliography>
- Full usage (README): <https://github.com/ContextLab/CDL-bibliography/blob/master/README.md>
- Tutorials: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/tutorials.md>
- How verification works: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/verification.md>

## Licence

MIT. See <https://github.com/ContextLab/CDL-bibliography/blob/master/LICENSE>.
