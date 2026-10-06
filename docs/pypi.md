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

With the install script (macOS and Linux), which works whatever the default Python is:

```bash
curl -LsSf https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/install.sh | sh
```

or, from a checkout of the repository, `sh install.sh`. The script installs `cdlbib`
with [uv](https://docs.astral.sh/uv/) in an environment of its own. When `uv` is missing
it says so and downloads it into `~/.local/share/cdlbib/uv/`; when no Python 3.11, 3.12
or 3.13 is installed, `uv` downloads one into its own folder. The `uv` that is downloaded
is one version, named by `UV_VERSION` in `install.sh`: its installer is run only when its
SHA-256 equals `UV_INSTALLER_SHA256` in `install.sh`, and that installer compares the
archive of `uv` with a SHA-256 it carries before unpacking it. No signature is verified.
To move to another version, set both values (the README's "Installation" section has the
command that prints the digest). The Python already installed
is not changed, no shell profile is edited and `sudo` is not used. `--ask` asks first,
`--no-uv` downloads no `uv`, `--uninstall` removes what the script installed, and
`--help` lists the options.

By hand, with Python 3.11 or later available:

```bash
uv tool install --python ">=3.11" "cdlbib @ git+https://github.com/ContextLab/CDL-bibliography"
pipx install --python python3.11 "cdlbib @ git+https://github.com/ContextLab/CDL-bibliography"
python3.11 -m pip install "cdlbib @ git+https://github.com/ContextLab/CDL-bibliography"
```

These commands and the `curl` form need the package to be on the repository's `master`
branch. Once `cdlbib` is published on PyPI, the same commands take `cdlbib` in place of
the quoted text (for example `python3.11 -m pip install cdlbib`), and the script takes
`--pypi`.

`pip` prints

```text
ERROR: Package 'cdlbib' requires a different Python: 3.9.13 not in '>=3.11'
```

when the Python it belongs to (here 3.9.13) is older than 3.11. The install script does
not use the default Python: `uv` finds a Python from 3.11 to 3.13, or downloads one, and
puts `cdlbib` into an environment made with it.

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
