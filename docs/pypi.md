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

## Requirements

Python 3.11 or later. The [GitHub CLI](https://cli.github.com) (`gh`) is needed for
recording reviews and for sending changes.

## Install

The package does not contain `cdl.bib`, so it is used inside a clone of the repository.
Install it from the clone:

```bash
git clone https://github.com/ContextLab/CDL-bibliography.git
cd CDL-bibliography
python -m pip install .
```

**`cdlbib` may not be published on PyPI yet.** Only if a release is listed at
<https://pypi.org/project/cdlbib/> does the following command work; the clone is still
needed for `cdl.bib`:

```bash
python -m pip install cdlbib
```

## Documentation

- Repository: <https://github.com/ContextLab/CDL-bibliography>
- Full usage (README): <https://github.com/ContextLab/CDL-bibliography/blob/master/README.md>
- Tutorials: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/tutorials.md>
- How verification works: <https://github.com/ContextLab/CDL-bibliography/blob/master/docs/verification.md>

## Licence

MIT. See <https://github.com/ContextLab/CDL-bibliography/blob/master/LICENSE>.
