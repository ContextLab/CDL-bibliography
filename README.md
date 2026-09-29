# Contextual Dynamics Laboratory's Bibliography Management Tool

![autocheck](https://github.com/ContextLab/CDL-bibliography/workflows/autocheck/badge.svg) ![citation check](https://github.com/ContextLab/CDL-bibliography/actions/workflows/citation-check.yml/badge.svg) [![DOI](https://zenodo.org/badge/69401856.svg)](https://zenodo.org/badge/latestdoi/69401856)

The main bibtex file ([cdl.bib](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib)) is shared by all documents produced by the [Contextual Dynamics Lab](https://www.context-lab.com/) at [Dartmouth College](https://www.dartmouth.edu/).

As of September 29, 2026, the 6,384 entries in `cdl.bib` have been checked against the published record. 6,361 entries match their source's metadata, and a person reviewed and approved 16 more against the source itself. The remaining 7 are waiting for review ([verification/2026-09-29-user-review/REVIEW.md](verification/2026-09-29-user-review/REVIEW.md)). New and edited entries are checked automatically on every pull request. "Verified" means the citation agrees with the published record. It does not guarantee the record is error-free, so please still look over the rendered bibliography of anything you submit.

## Contents:
- [What can you use this repository for?](#what-can-you-use-this-repository-for)
- [Using `cdl.bib`](#using-cdlbib)
- [Using the bibtex checker tools](#using-the-bibtex-checker-tools)
  - [Installation](#installation)
  - [Overview](#overview)
- [Suggested workflow](#suggested-workflow)
- [What belongs in `cdl.bib`](#what-belongs-in-cdlbib)
- [Additional information and usage instructions](#additional-information-and-usage-instructions)
  - [`bibcheck verify`](#verify)
  - [`bibcheck compare`](#compare)
  - [`bibcheck commit`](#commit)
  - [`bibcheck crossref`: citation verification](#crossref-citation-verification)
- [Using the bibtex file as a common bibliography for all *local* LaTeX files](#using-the-bibtex-file-as-a-common-bibliography-for-all-local-latex-files)
  - [General Unix/Linux Setup (Command Line Compilation)](#general-unixlinux-setup-command-line-compilation)
  - [MacOS Setup with TeXShop and TeX Live](#macos-setup-with-texshop-and-tex-live)
- [Using the bibtex file on Overleaf](#using-the-bibtex-file-on-overleaf)
- [Using the bibtex file as a submodule of a paper's repository](#using-the-bibtex-file-as-a-submodule-of-a-papers-repository)
- [Running the tests](#running-the-tests)
- [Acknowledgements](#acknowledgements)

# What can you use this repository for?
The main components of this repository are:
1. A bibtex file containing the bibliographic information
2. A set of bibtex checker tools that verify the formatting *and* the accuracy of the bibtex file

## Using `cdl.bib`
You may find the included bibtex file and/or readme file useful for any of the following:
- Provides a "pre seeded" bibtex file, checked against the published record, that you can reference in your LaTeX documents
- A means of organizing a set of papers related to psychology, neuroscience, math, and machine learning
- A template for a new bibtex file that you want to start
- Instructions for configuring a system-referenced bibtex file that can be referenced by any LaTeX file on your local machine
- Instructions for using the bibliography in Overleaf projects and as a submodule of a paper's GitHub repository

## Using the bibtex checker tools

The checker (`bibcheck.py`) does two complementary jobs:

1. **Formatting** (`bibcheck.py verify`, `compare`, and `commit`) checks that every entry follows the lab's conventions:
   - Checks key naming conventions
   - Validates author/editor name formatting
   - Ensures proper capitalization
   - Verifies page number formatting
   - Detects duplicate entries

2. **Accuracy** (`bibcheck.py crossref`) checks each entry against the published record:
   - Looks up the entry by DOI (or searches by title and authors) in [Crossref](https://www.crossref.org/)
   - Falls back to other sources when Crossref can't settle it: PubMed/Europe PMC, publisher full text, library catalogues (for books), preprint servers (arXiv, bioRxiv, PsyArXiv), DataCite (for software and data), the ACL Anthology, and the Society for Neuroscience abstract archive
   - Requires every field in the entry (title, all authors in order, year, venue, volume, issue, pages, DOI, ...) to agree with the source
   - Never guesses: when the evidence is incomplete or conflicting, the entry is flagged for review instead of being accepted
   - Remembers what has been checked, so only new or edited entries are checked again

You may find these tools useful for:
- Verifying the integrity and accuracy of a .bib file
- Autocorrecting the formatting of a .bib file (use with caution!)
- Automatically generating change logs and commit messages
- Finding and fixing metadata errors

`python bibverify.py` still works, but it now runs the same accuracy checker as `bibcheck.py crossref`. The older parallel, fuzzy-matching verifier (and its `--workers` option) has been retired.

### Installation
The bibtex checker is used on macOS and tested automatically on Linux (Ubuntu), both with Python 3.11. Windows is untested.

After cloning this repository, create a virtual environment and install the dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python bibcheck.py --help
```

The accuracy checker contacts Crossref and other public services, which ask that you identify yourself. Set a real contact address before running it (or pass `--mailto`):

```bash
export CROSSREF_MAILTO='your.name@dartmouth.edu'
```

### Overview

`bibcheck.py` has the following commands (a summary; run `python bibcheck.py --help` for the full list):

```bash
Commands:
  verify    Format check, then citation verification of new/edited entries
  compare   Show the differences between two .bib files
  commit    Run the verify gate, then commit only the bibliography file
  crossref  Check citation accuracy against external evidence (never edits BibTeX)
  magic     Legacy: autofix, overwrite cdl.bib and commit (not recommended)
```

Run `python bibcheck.py COMMAND --help` for the options of any command.

# Suggested workflow

After making changes to `cdl.bib` (manually, using
[BibDesk](https://bibdesk.sourceforge.io/), etc.), please follow the suggested
workflow below in order to safely update the shared lab resource:

1. Check the formatting of the modified file *and* the accuracy of every new or edited entry (correct any problems until this passes):
```bash
python bibcheck.py verify --verbose
```
   The formatting check covers the whole file. The accuracy check covers only the entries that are new or changed compared with the `master` branch on GitHub, so it takes seconds rather than hours.

2. If an entry fails the accuracy check, look at the issues printed for it (they are also saved in `.bibcheck/report.jsonl`). Usually the fix is to correct the entry to match the actual paper: a wrong page range, a missing author, a preprint cited where the published version was meant, and so on. Then run step 1 again. If you are certain the entry is right but it can't be checked automatically (e.g., an old book with no online record), see [Human review](#human-review).

3. Generate a change log and commit your changes:
```bash
python bibcheck.py commit --verbose
```
   `commit` runs the same checks as `verify` and refuses to commit if anything fails. It commits only the bibliography file.

4. Push your changes to your fork:
```bash
git push
```

5. Create a pull request for pulling your changes into the ContextLab fork. The pull request is checked automatically: formatting and tests (`autocheck`), and the accuracy of every new or edited entry (`Citation verification`).

# What belongs in `cdl.bib`

These are the lab's rules for what an entry must look like and when an entry is left out. The full decision log, with the reasoning and every case they were applied to, is in [verification/resolution-plan-2026-09-22/README.md](verification/resolution-plan-2026-09-22/README.md).

- **Cite the work as printed.** Every field should match the official published record, up to the formatting conventions below. If the published version and a preprint differ, cite the one you actually mean.
- **The printed paper wins.** Normally the publisher's metadata (e.g., in Crossref) is taken as the record. When there is reason to doubt it, such as a correction notice, sources that disagree with each other, or a lab member's flag, the paper as printed decides.
- **No conference abstracts.** Short meeting abstracts are not citable publications and are not kept. Full papers in conference *proceedings* are fine. Before dropping something as an abstract, check that it really is one.
- **If it can't be verified, leave it out.** An entry that can't be verified, even after searching the web for evidence, is dropped. So is an entry whose details stay ambiguous after research. It can always be added back once the evidence turns up.

# Additional information and usage instructions

## `verify`

You can run the `verify` command using:
```bash
python bibcheck.py verify --fname <fname>
```
where `<fname>` is the name of the .bib file whose integrity you want to check (the default is `cdl.bib`).
For help, run:
```bash
python bibcheck.py verify --help
```

`verify` runs three checks in order:
1. The **formatting check** described below, on every entry.
2. The **accuracy check** (`crossref verify --auto-review`) on the entries that are new or edited compared with the GitHub `master` version of `cdl.bib`. An entry whose only change is its key is not re-checked.
3. A **status line** summarizing how many entries in the whole library are verified.

It exits with `1` if the formatting check fails or any new or edited entry can't be verified, and prints each problem entry with its issues. It exits with `2` if the accuracy check can't run at all (for example, no contact address is set or a service is down). Useful options: `--no-citations` for an offline, formatting-only check; `--all` to check the accuracy of every entry, not just changed ones; `--reference other.bib` to compare against a different base file.

The formatting check verifies the following:
- Proper bibtex key naming:
  - Keys for single-author papers are named with the first four letters of the author's surname, plus the last two digits of the publication year (e.g., Mann21)
  - Keys for dual-author papers are named with the first four letters of the first author's surname, followed by the first four letters of the second author's surname, followed by the last two digits of the publication year (e.g., MannKaha21)
  - Keys for papers with three or more authors are named with the first four letters of the first author's surname, followed by "Etal", followed by the last two digits of the publication year (e.g. MannEtal21)
  - Surnames with fewer than four letters result in shorter keys (e.g. LeeEtal21)
  - Titles (e.g., Dr., Hon., etc.) and suffixes (e.g., Jr., Sr., II, III, etc.) are omitted from key names
  - Multi-word surnames (e.g., y Cajal, van der Meer, etc.) are concatenated into a single "word" without changing any capitalization, for the purposes of generating a key (e.g., yCaj05, vandEtal21, etc.)
  - An organization or group author (written fully in curly braces, e.g., `{{R Core Team}}`) counts as one author. Its part of the key uses the letters of successive words of the name until four letters are reached (e.g., `{R Core Team}` gives RCor12, `{U.S. Food and Drug Administration}` gives USFo20)
  - All unicode characters are converted to their nearest ASCII counterparts (e.g., "é" is converted to "e", etc.)
  - In-press, submitted, under revision, or other "unpublished" manuscripts should use the last two digits of the *submission* year
  - Bibtex keys may not be duplicated.  If two or more entries share the same "base" bibtex key, they should be renamed to make each key unique by adding a suffix to the key: MannEtal21a, MannEtal21b, etc.  If a bibtex key requires a suffix, *all* bibtex keys that share the same base must also have suffixes.  Suffixes must be assigned in order (e.g., if MannEtal21a and MannEtal21c are in the .bib file, then either MannEtal21b must also be in the .bib file, or MannEtal21c must be renamed to MannEtal21b).  Likewise, a key that no longer shares its base with any other entry drops its suffix.
- Proper formatting of author and editor names:
  - The name must appear in the following order with no commas: First Middle Surname(s) Suffixes
  - Multi-word surnames should be enclosed in curly braces (e.g., "{van der Meer}")
  - Latex accents (e.g. "\\'{e}" or "{\\' e}") are supported
  - Initials must be separated (e.g., "AA" becomes "A A")
  - Hyphenated initials and/or names should *not* be separated (e.g., "H-T" is correct as is)
  - For multi-author (or multi-editor) papers, names should be separated by the string " and " (note single spaces on either side)
- Detection of duplicate entries.  Entries are considered to be duplicates if they share the same author last names *and* the publications also share the same title.  Importantly, publication year, journal name, and other fields are *not* considered in detecting duplicates; this enables the duplicate checker to catch problems like a publication being entered for a preprint that is already in the database, rather than updating the existing entry.  Inspect proposed duplicate removals carefully.
- Page numbering must be properly formatted:
  - Articles with single pages should contain only one page number (e.g. "3--3" should be "3")
  - Page ranges are denoted using an n-dash with no spaces (e.g., "3--10")
  - The first page in the given range must be strictly smaller than the last page in the given range
  - For journals with page-number prefixes (e.g., "e2910"), the same prefix must be used for both the start and end of the page range, and the numbering must be valid (i.e., the first page must be strictly smaller than the last page)
  - Roman numerals are supported and subjected to the same constraints as integer pages.  They may be uppercase or lowercase, but may not be mixed case.
  - Article numbers and electronic locators that a journal prints instead of page numbers are kept as printed
  - Some types of errors may be autocorrected, although this must be treated with caution to ensure accuracy (e.g. "1002 - 15" may be autocorrected to "1002--1015")
- Journal names must be properly capitalized and written out in full (e.g., "J. Neurosci" becomes "The Journal of Neuroscience").
- Book titles must be properly capitalized and written out in full.
- Article titles must be capitalized in sentence case, including the first word after a colon (e.g., "Memory: the review", not "Memory: The review").  Proper nouns and acronyms are protected with curly braces (e.g., "{fMRI} of the {Stroop} task").  Titles may not be (fully) enclosed in curly braces and may not end in '.'.  The checker can't tell a proper noun from an ordinary word, and it doesn't catch a capital "A" after a colon ("Memory: A review" passes), so check titles against the source.
- Publisher names must be written out in full.
- Addresses must be formatted properly:
  - US states are abbreviated with their two-letter codes, in curly braces (e.g., "Cambridge, Massachusetts" and "Cambridge, Mass." both become "Cambridge, {MA}")
  - City names should be written out in full (e.g., "New York, {NY}", not "NY, NY").  The checker doesn't catch this one, or a spelled-out state it doesn't recognize, so please write these carefully.
  - The checker never adds a country the source doesn't print.  It does drop the country after some well-known cities (e.g., "Berlin, Germany" becomes "Berlin").
  - Abbreviations should not contain periods (".")
- Only the following fields are allowed (see [keep_fields.txt](bibcheck/keep_fields.txt)): author, title, year, journal, booktitle, volume, number, pages, doi, publisher, editor, edition, series, chapter, school, institution, organization, address, type, howpublished, and force
- To override autoformatting or checks for a given entry, add an additional field, "force", to that bibtex entry and set its value to "True".  Most formatting checks are skipped for that entry (duplicate detection and malformed page ranges are still checked).  This is useful if the above rules cannot be properly applied to a given entry.  `force` does **not** skip the accuracy check.

If errors are found, they are printed to the terminal along with suggested corrections (if available).

***Danger zone***: `autofix`

The bibtex checker can attempt to automatically correct formatting issues using the `--autofix` and `--outfile` flags.  The `--verbose` flag is also strongly encouraged when the `--autofix` flag is used.  Autocorrect mode may be used as follows:
```bash
python bibcheck.py verify --autofix --verbose --no-citations --outfile=cleaned.bib
```
This will create a new .bib file, cleaned.bib, based on cdl.bib-- but with all fields and entries autocorrected where possible.  After manually checking the new "autocorrected" .bib file, cdl.bib may be overwritten with `cleaned.bib`:
```bash
mv cleaned.bib cdl.bib
```

This mode can easily introduce errors if not checked (manually!) carefully.  It is included for convenience (e.g., to facilitate very large numbers of simple changes), but it should not normally be used.  (The legacy `magic` command does all of this in one step, without giving you a chance to check the result, and then commits it.  Please don't use it.)

## `compare`
You can run the `compare` command using:
```bash
python bibcheck.py compare <fname1> <fname2>
```
where `<fname1>` is the name of the "original" .bib file and `<fname2>` is the
name of the "new" .bib file.  The `compare` function will run a check to
determine if there are any differences between fname2 and fname1.  For help, run:
```bash
python bibcheck.py compare --help
```

Given two .bib files, any *differences* between the files are detected and printed.  Differences can include:
- New or deleted items
- Modified entries (e.g., new, deleted, or modified fields)

## `commit`
You can run the `commit` command using:
```bash
python bibcheck.py commit
```
For help, run:
```bash
python bibcheck.py commit --help
```

The `commit` command first runs the same checks as `verify` (formatting, plus the
accuracy of new and edited entries), and refuses to commit if any of them fail.
If the checks pass, the `compare` command is used to compare the local cdl.bib
file to the version stored in the `master` branch of the `ContextLab` fork.
Only the bibliography file is then committed to the local repository (using
`git commit`), with a commit message describing what was added, removed, and
changed.

In order for the commits to be pushed, the `git push` command must still be
called, and a pull request must be submitted in order to integrate the changes
into the main ContextLab fork.

## `crossref`: citation verification

`python bibcheck.py crossref` is the accuracy checker on its own, with more control than `verify` gives you. It never edits `cdl.bib`; it only reports.

```bash
# Check new and edited entries (and retry any that hit a network error)
python bibcheck.py crossref verify cdl.bib --auto-review

# Check the whole library, starting from the lab's saved results
python bibcheck.py crossref restore verification/baseline.jsonl.gz
python bibcheck.py crossref verify cdl.bib --auto-review

# Offline: how many entries are verified right now?
python bibcheck.py crossref status cdl.bib

# Only the references in your manuscript (one citation key per line)
python bibcheck.py crossref status cdl.bib --keys manuscript-keys.txt
```

### How an entry is checked

The checker first looks up the entry's DOI in Crossref. If there's no DOI, it searches Crossref by title and authors and compares the top candidates. A close title alone is never enough: to be verified, the entry's title, full author list (in order), year, and venue must match the source, and so must every other field the entry has (volume, issue, pages, publisher, DOI, and so on). A DOI that points to a different paper is reported, not silently replaced.

When Crossref can't settle an entry, the checker tries the other free sources in turn: PubMed records (through Europe PMC), the publisher's own front matter in open-access full text, library catalogues for books, preprint servers (arXiv, bioRxiv, PsyArXiv), DataCite for software and datasets, the ACL Anthology, and the Society for Neuroscience abstract archive (which can identify an abstract, though [abstracts themselves aren't kept](#what-belongs-in-cdlbib)). Each source is only trusted for what it actually records. For example, a preprint server's record can verify a preprint but not the journal version.

If a correction, erratum, retraction, or expression of concern is linked to an entry, the entry is flagged for review. A retraction or expression of concern keeps it flagged. A correction that couldn't be read can be accepted when Crossref and Europe PMC show no retraction; the result then records that the notice was not read.

### What the results mean

| Status | Meaning | Counts as verified? |
|-|-|-|
| `metadata_verified` | Every field agrees with a trusted source (automatically, or through the research evidence described below) | Yes |
| `human_verified` | A named person checked this exact entry against the source and recorded their approval | Yes |
| `needs_review` | Missing evidence, a disagreement with the source, ambiguity, or an unsupported field | No |
| `provider_error` | A network or service failure prevented the check; it is retried next time | No |
| `pending` | Not checked yet (e.g., the entry was just edited) | No |

`crossref verify` and `crossref status` exit with `0` when every selected entry is verified, `1` when some aren't, and `2` for a configuration, parsing, or network error. Add `--require-human` to `status` if you want to accept only `human_verified` entries.

### Saved results and automatic re-checking

Results are saved in `.bibcheck/verification.sqlite3` (a local, git-ignored file), so each entry is checked only once. Every entry has a fingerprint of its exact text (ignoring the key). Editing an entry in any way, even just its formatting, invalidates its result, and it is checked again next time. Renaming a key does not.

The lab's results for the whole library are shared in [verification/baseline.jsonl.gz](verification/baseline.jsonl.gz). `crossref restore` loads them into your local database; `crossref snapshot` writes a new one. A restored result applies only to an entry whose text is exactly the same.

### Automatic checks on pull requests

The `Citation verification` workflow runs on every pull request to `master`, and on every push to `master`. It takes the base branch's `cdl.bib` and its saved results, and checks every entry that is new or edited in the pull request. The check fails unless all of them are verified. Unchanged entries are not checked again. Saved approvals come only from the base branch (the workflow also reuses its own cache of earlier checks), so a pull request can't approve its own entries. Running the workflow by hand from the Actions tab checks the whole library.

The workflow needs the repository's Actions variable `CROSSREF_MAILTO` to be set to a real contact address.

### Human review

Some entries can't be verified automatically: an old book with no online record, a scanned chapter, a record with an error you can see in the printed paper. If you have checked the entry against the actual source, you can record that:

```bash
# 1. Export the entry, its fingerprint, and what the checker found
python bibcheck.py crossref review-packet CiteKey --output review-packet.json

# 2. After checking the source, record your approval
python bibcheck.py crossref approve CiteKey \
  --fingerprint HASH_FROM_REVIEW_PACKET \
  --reviewer 'Your name' \
  --source 'URL or physical edition you checked' \
  --note 'Which fields you checked, and why the automatic check failed'
```

The approval is tied to the entry's exact text: if the entry is edited later, it has to be approved again. An approval recorded in error can be withdrawn with `python bibcheck.py crossref revoke CiteKey --by 'Who decided' --reason 'Why'`. The revocation is logged in `verification/revocations.jsonl` and the entry goes back to `needs_review`. Restoring an older snapshot can't bring the approval back, but a new `approve` with a new note can. To share it, export the updated results (`python bibcheck.py crossref snapshot verification/baseline.jsonl.gz`) and commit them with your change. Because the pull request check trusts only the results already on `master`, it will still fail for that entry on your pull request. Say so in the pull request; a maintainer who has checked your approval can merge it, and from then on the entry counts as verified.

### Research evidence

In September 2026 the lab checked the entries that no automatic source could settle, one at a time. Each field was matched to a quotation from an official source (a publisher's page, a scanned table of contents, a library catalogue record, and so on). Those findings are saved under [verification/](verification/). `python bibcheck.py crossref research-approve` turns them into `metadata_verified` results, but only when every field of the entry matches a saved quotation. See [verification/research-route-2026-09-27/README.md](verification/research-route-2026-09-27/README.md) for the details.

There is also an optional tool that uses a language model to find a paper's PDF and quote the relevant passages (`crossref research` and `research-batch`). Its findings are evidence for a person to review; it never approves an entry by itself. See [docs/verification.md](docs/verification.md).

### Being polite to Crossref

Requests go out one at a time, with at least half a second between them (one second by default), and the checker backs off when a service asks it to. Responses are cached, so re-running a check doesn't repeat requests. Please don't run several checks at once from the same machine. See [Crossref's guidance for API users](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).

More detail on how verification works, including every acceptance rule, is in [docs/verification.md](docs/verification.md). The dated reports in [verification/](verification/) record how the library was brought to its current state.

# Using the bibtex file as a common bibliography for all *local* LaTeX files

## General Unix/Linux Setup (Command Line Compilation)
1. Check out this repository to your home directory
2. Add the following line to your `~/.bash_profile` (or `~/.zshrc`, etc.).  The trailing colon keeps TeX's default search locations:
```
export BIBINPUTS="$HOME/CDL-bibliography:$BIBINPUTS:"
```
3. Run (in terminal): `source ~/.bash_profile`
4. In your .tex file, use the line `\bibliography{cdl}` to generate a bibliography using the citation keys that were defined in cdl.bib and used in the current file.
5. To compile your document (filename.tex) and generate its bibliography and a pdf (filename.pdf), run:
```
pdflatex filename
bibtex filename
pdflatex filename
pdflatex filename
```

## MacOS Setup with TeXShop and TeX Live

Mac GUI applications like TeXShop don't execute within your shell environment, which means the environment variable approach described above won't work when compiling through the TeXShop GUI. Instead, use TeX Live's built-in support for personal files:

1. Check out this repository (we'll assume you cloned it to your home directory: `~/CDL-bibliography`)
2. Create the TeX Live personal texmf directory structure for bibliography files:
```bash
mkdir -p ~/Library/texmf/bibtex/bib
```
3. Create a symbolic link from your personal texmf directory to the CDL-bibliography repository. **Important**: You must use the absolute path (not relative paths or `~`):
```bash
ln -s /Users/YOUR_USERNAME/CDL-bibliography/cdl.bib ~/Library/texmf/bibtex/bib/cdl.bib
```
Replace `YOUR_USERNAME` with your actual macOS username, or use `$HOME` instead:
```bash
ln -s $HOME/CDL-bibliography/cdl.bib ~/Library/texmf/bibtex/bib/cdl.bib
```
4. In your .tex file, use the line `\bibliography{cdl}` to generate a bibliography using the citation keys defined in cdl.bib
5. Compile your document using TeXShop's GUI or from the command line

**Note**: This approach also works for command-line compilation, so you don't need to set up the environment variables if you use this method.

# Using the bibtex file on Overleaf
Overleaf projects [can't contain git submodules](https://docs.overleaf.com/integrations-and-add-ons/git-integration-and-github-synchronization/github-synchronization), so (unlike what earlier versions of this readme suggested) you can't add this repository to an Overleaf project as a submodule.  Instead, either:
- Upload `cdl.bib` to your project, or
- Use Overleaf's [Add from External URL](https://docs.overleaf.com/managing-projects-and-files/adding-files-to-a-project/adding-a-file-from-a-url) option with the [raw bibliography](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib).  The linked file is updated only when you refresh it, so refresh it when you want the latest version (and check the resulting citations).

Either way, change the `\bibliography{...}` line in your .tex file to `\bibliography{cdl}`.

# Using the bibtex file as a submodule of a paper's repository
If you write your paper in a git repository of your own (outside Overleaf), you can use a [git submodule](https://github.blog/2016-02-01-working-with-submodules/) to keep a reference to this repository that you can easily keep in sync with the latest version:
1. Navigate to your paper's repository (in Terminal) and then run
```
git submodule add https://github.com/ContextLab/CDL-bibliography.git
```
2. Inside your .tex source file, change the `\bibliography{cdl}` line to `\bibliography{CDL-bibliography/cdl}`.
3. Commit your changes (`git commit -a -m "added CDL bibliography as a submodule"`) and then push them (`git push`).
4. To pull the latest changes from the CDL-bibliography repository, run `git submodule update --remote CDL-bibliography` inside your paper's repository, then commit the updated submodule.
5. When you clone a fresh repository that includes this repository (or others) as a submodule, run the following commands to download the contents of the submodule repositories:
```
git submodule init
git submodule update
```

Whichever setup you use, it's a good idea to keep a copy of the bibliography with each submitted manuscript, so that later edits to the shared file don't change that submission's references.

# Running the tests

To run the full test suite:
```bash
python -m pip install -r requirements-research.txt pytest
export CROSSREF_MAILTO='your.name@dartmouth.edu'
python -m pytest tests
python bibcheck/test.py
```

Almost all tests use saved copies of real source records, so they run offline. Four tests call the live Crossref API, so they need a network connection and `CROSSREF_MAILTO`, and can fail temporarily if Crossref is down. Eight tests read PDFs from a local paper library and are skipped when it isn't available. `bibcheck/test.py` runs the formatting check on `cdl.bib`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a citation, and [docs/verification.md](docs/verification.md) for how verification works.

# Acknowledgements
This bibtex file is built on a large bibtex file authored by Michael Kahana's
[Computational Memory Lab at the University of Pennsylvania](https://memory.psych.upenn.edu/).
However, this version is not kept in sync with the CML's version.  [Several members](https://github.com/ContextLab/CDL-bibliography/graphs/contributors) of the [Contextual Dynamics Lab](https://www.context-lab.com/) have contributed to the current version.

This repository is provided as a courtesy, and we make no claims with respect to accuracy, completeness, etc.
