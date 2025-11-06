# Contextual Dynamics Laboratory's Bibliography Management Tool

![autocheck](https://github.com/ContextLab/CDL-bibliography/workflows/autocheck/badge.svg) [![DOI](https://zenodo.org/badge/69401856.svg)](https://zenodo.org/badge/latestdoi/69401856)

The main bibtex file ([cdl.bib](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib)) is shared by all documents produced by the [Contextual Dynamics Lab](http://www.context-lab.com) at [Dartmouth College](http://www.dartmouth.edu).

## Contents:
- [What can you use this repository for?](#what-can-you-use-this-repo-for)
- [Using `cdl.bib`](#using-cdlbib)
- [Using the bibtex checker tools](#using-the-bibtex-checker-tools)
  - [Installation](#installation)
  - [Overview](#overview)
  - [bibcheck.py - Format Verification](#bibcheckpy---format-verification)
  - [bibverify.py - Accuracy Verification](#bibverifypy---accuracy-verification)
- [Suggested workflow](#suggested-workflow)
- [Additional information and usage instructions](#additional-information-and-usage-instructions)
  - [`bibcheck verify`](#verify)
  - [`bibcheck compare`](#compare)
  - [`bibcheck commit`](#commit)
- [Using the bibtex file as a common bibliography for all *local* LaTeX files](#using-the-bibtex-file-as-a-common-bibliography-for-all-local-latex-files)
  - [General Unix/Linux Setup (Command Line Compilation)](#general-unixlinux-setup-command-line-compilation)
  - [MacOS Setup with TeXShop and TeX Live](#macos-setup-with-texshop-and-tex-live)
- [Using the bibtex file on Overleaf](#using-the-bibtex-file-on-overleaf)
- [Acknowledgements](#acknowledgements)

# What can you use this repository for?
The main components of this repository are:
1. A bibtex file containing the bibliographic information
2. A set of bibtex checker tools that are used to verify the integrity of the bibtex file

## Using `cdl.bib`
You may find the included bibtex file and/or readme file useful for any of the following:
- Provides a "pre seeded" bibtex file that you can configure to be referenced in your LaTeX documents
- A means of organizing a set of papers related to psychology, neuroscience, math, and machine learning
- A template for a new bibtex file that you want to start
- Instructions for configuring a system-referenced bibtex file that can be referenced by any LaTeX file on your local machine
- Instructions for adding this repository as a sub-module to Overleaf projects, so that you can share a common bibtex file across your Overleaf projects

## Using the bibtex checker tools

This repository includes two complementary verification tools:

1. **bibcheck.py** - Verifies formatting and consistency
   - Checks key naming conventions
   - Validates author/editor name formatting
   - Ensures proper capitalization
   - Verifies page number formatting
   - Removes duplicate entries

2. **bibverify.py** - Verifies accuracy against external sources
   - Cross-references entries with CrossRef database (170M+ records)
   - Validates volume, issue/number, and page fields
   - Detects common errors (e.g., DOI in pages field)
   - Uses conservative matching to prevent false positives

You may find these tools useful for:
- Verifying the integrity and accuracy of a .bib file
- Autocorrecting a .bib file (use with caution!)
- Automatically generating change logs and commit messages
- Finding and fixing metadata errors

### Installation
The bibtex checker has only been tested on MacOS, but it will probably work without modification on other Unix systems, and with minor modification on Windows systems.

To install the bibtex checker, you must first have a recent version of Python (3.5+) and [pip](https://pip.pypa.io/en/stable/installing/).  After cloning this repository, install the dependencies by running:

```bash
pip install -r requirements.txt
```

### Overview

#### bibcheck.py - Format Verification

The format verification tool has three main functions: `verify`, `compare`, and `commit`:
```bash
Usage: bibcheck.py [OPTIONS] COMMAND [ARGS]...

Options:
  --install-completion  Install completion for the current shell.
  --show-completion     Show completion for the current shell, to copy it or
                        customize the installation.

  --help                Show this message and exit.

Commands:
  commit
  compare
  verify
```

#### bibverify.py - Accuracy Verification

The accuracy verification tool checks entries against the CrossRef database:
```bash
Usage: python bibverify.py [OPTIONS] COMMAND [ARGS]...

Commands:
  verify  Verify bibliographic entries against CrossRef database
  info    Show information about the verification tool
```

**Key Features:**
- **Fast:** Verifies 6,151 entries in ~6 minutes using parallel processing
- **Conservative:** Requires strong similarity in title, authors, AND journal before reporting issues
- **Accurate:** Prevents false positives by rejecting uncertain matches
- **Focused:** Only checks volume, issue, and pages metadata (not formatting)

**Basic Usage:**
```bash
# Verify entire bibliography with 10 parallel workers
python bibverify.py verify cdl.bib --workers 10

# Get detailed output
python bibverify.py verify cdl.bib --verbose --workers 10

# Save report to file
python bibverify.py verify cdl.bib --workers 10 > verification_report.txt 2>&1
```

**How it Works:**
1. Queries CrossRef API by DOI (if present) or by title/authors
2. **Conservative Matching:** Requires ALL of:
   - Title similarity ≥ 85%
   - Author similarity ≥ 70%
   - Journal similarity ≥ 60%
   - Year difference ≤ 1 year
3. Only reports discrepancies when confident it's the same paper
4. Checks for volume/number mismatches, incorrect pages, and common errors

**Example Output:**
```
============================================================
VERIFICATION SUMMARY
============================================================
✓ Verified: 3,988 (65%)
✗ Errors: 724 (12%)
⚠ Warnings: 1,434 (23%)

Common errors found:
- Volume/issue number mismatches
- Page range errors or off-by-one issues
- DOI placed in pages field instead of doi field
- Year discrepancies (preprint vs published versions)
```

**Performance:** With 10 workers, verifies ~17 entries/second. Full bibliography verification takes approximately 6 minutes.

**Note:** 23% of entries may not be found in CrossRef (arXiv preprints, technical reports, very new/old publications). The tool correctly rejects uncertain matches rather than suggesting false corrections.

# Suggested workflow

After making changes to `cdl.bib` (manually, using
[bibdesk](https://bibdesk.sourceforge.io/), etc.), please follow the suggested
workflow below in order to safely update the shared lab resource:

1. **(Optional) Verify accuracy against CrossRef:**
```bash
python bibverify.py verify cdl.bib --workers 10 > verification_report.txt 2>&1
# Review verification_report.txt and fix any genuine errors found
```

2. Verify the formatting/integrity of the modified cdl.bib file (correct any changes until this passes):
```bash
python bibcheck.py verify --verbose
```

3. Generate a change log and commit your changes:
```bash
python bibcheck.py commit --verbose
```

4. Push your changes to your fork:
```bash
git push
```

5. Create a pull request for pulling your changes into the ContextLab fork

**Note:** The bibverify step is optional but recommended for catching metadata errors. It's especially useful when adding new entries or updating existing ones.

## Additional information and usage instructions

### `verify`

You can run the `verify` command using:
```bash
python bibcheck.py verify <fname>
```
where `<fname>` is the name of the .bib file whose integrity you want to check.
For help, run:
```bash
python bibcheck.py verify --help
```

The `verify` function checks the format of an arbitrary .bib file and verifies the following information:
- Proper bibtex key naming:
  - Keys for single-author papers are named with the first four letters of the author's surname, plus the last two digits of the publication year (e.g., Mann21)
  - Keys for dual-author papers are named with the first four letters of the first author's surname, followed by the first four letters of the second author's surname, followed by the last two digits of the publication year (e.g., MannKaha21)
  - Keys for papers with three or more authors are named with the first four letters of the first author's surname, followed by "Etal", followed by the last two digits of the publication year (e.g. MannEtal21)
  - Surnames with fewer than four letters result in shorter keys (e.g. LeeEtal21)
  - Titles (e.g., Dr., Hon., etc.) and suffixes (e.g., Jr., Sr., II, III, etc.) are ommitted from key names
  - Multi-word surnames (e.g., y Cajal, van der Meer, etc.) are concatenated into a single "word" without changing any capitalization, for the purposes of generating a key (e.g., yCaj05, vandEtal21, etc.)
  - All unicode characters are converted to their nearest ASCII counterparts (e.g., "é" is converted to "e", etc.)
  - In-press, submitted, under revision, or other "unpublished" manuscripts should use the last two digits of the *submission* year
  - Bibtex keys may not be duplicated.  If two or more entries share the same "base" bibtex key, they should be renamed to make each key unique by adding a suffix to the key: MannEtal21a, MannEtal21b, etc.  If a bibtex key requires a suffix, *all* bibtex keys that share the same base must also have suffixes.  Suffixes must be assigned in order (e.g., if MannEtal21a and MannEtal21c are in the .bib file, then either MannEtal21b must also be in the .bib file, or MannEtal21c must be renamed to MannEtal21b).
- Proper formatting of author and editor names:
  - The name must appear in the following order with no commas: First Middle Surname(s) Suffixes
  - Multi-word surnames should be enclosed in curly braces (e.g., "{van der Meer}")
  - Latex accents (e.g. "\\'{e}" or "{\\' e}") are supported
  - Initials must be separated (e.g., "AA" becomes "A A")
  - Hyphenated initials and/or names should *not* be separated (e.g., "H-T" is correct as is)
  - For multi-author (or multi-editor) papers, names should be separated by the string " and " (note single spaces on either side)
- Removal of duplicate entries.  Entries are considered to be duplicates if they share the same author last names *and* the publications also share the same title.  Importantly, publication year, journal name, and other fields are *not* considered in detecting duplicates; this enables the duplicate checker to catch problems like a publication being entered for a preprint that is already in the database, rather than updating the existing entry.
- Page numbering must be properly formatted:
  - Articles with single pages should contain only one page number (e.g. "3--3" should be "3")
  - Page ranges are denoted using an n-dash with no spaces (e.g., "3--10")
  - The first page in the given range must be strictly smaller than the last page in the given range
  - For journals with page-number prefixes (e.g., "e2910"), the same prefix must be used for both the start and end of the page range, and the numbering must be valid (i.e., the first page must be strictly smaller than the last page)
  - Roman numerals are supported and subjected to the same constraints as integer pages.  They may be uppercase or lowercase, but may not be mixed case.
  - Some types of errors may be autocorrected, although this must be treated with caution to ensure accuracy (e.g. "1002 - 15" may be autocorrected to "1002--1015")
- Journal names must be properly capitalized and written out in full (e.g., "J. Neurosci" becomes "The Journal of Neuroscience").  Ampersands ("&") must be converted to "and".
- Book titles must be properly capitalized and written out in full.  Ampersands ("&") must be converted to "and".
- Article titles must be capitalized in sentence case (with exceptions blocked out in curly braces).  Titles may not be (fully) enclosed in curly braces and may not end in '.'.
- Publisher names must be written out in full.  Ampersands ("&") must be converted to "and".
- Addresses must be formatted properly:
  - State names and non-US countries are abbreviated with two-letter codes (e.g., "New York, New York" should be "New York, NY")
  - Address names should be written out in full (e.g., "NY, NY" should be "New York, NY")
  - Abbreviations should not contain periods (".")
- Only the following (standard) fields are allowed: year, volume, title, pages, number, journal, author, booktitle, publisher, editor, school, chapter, address, organization
- To override autoformatting or checks for a given entry, add an additional field, "force" to that bibtex entry and set its value to "True".  No checks will be performed for that entry.  (This is useful if the above rules cannot be properly applied to a given entry.)

If errors are found, they are printed to the terminal along with suggested corrections (if available).

***Danger zone***: `autofix`

The bibtex checker can attempt to automatically correct formatting issues using the `--autofix` and `--outfile` flags.  The `--verbose` flag is also strongly encouraged when the `--autofix` flag is used.  Autocorrect mode may be used as follows:
```bash
python bibcheck.py verify --autofix --verbose --outfile=cleaned.bib
```
This will create a new .bib file, cleaned.bib, based on cdl.bib-- but with all fields and entries autocorrected where possible.  After manually checking the new "autocorrected" .bib file, cdl.bib may be overwritten with `cleaned.bib`:
```bash
mv cleaned.bib cdl.bib
```

This mode can easily introduce errors if not checked (manually!) carefully.  It is included for convenience (e.g., to facilitate very large numbers of simple changes), but it should not normally be used.

### `compare`
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

### `commit`
You can run the `commit` command using:
```bash
python bibcheck.py commit
```
For help, run:
```bash
python bibcheck.py commit --help
```

By default, the `commit` command first uses the `verify` command to check the
local cdl.bib file's integrity.  If the check succeeds, the `compare` command
is then used to compare the local cdl.bib file to the version stored in the
`master` branch of the `ContextLab` fork.  The changes are then "committed" to
the local github repository (using ```git commit```), and a commit message is
added to the commit describing what was changed. 

In order for the commits to be pushed, the ```git push``` command must still be
called, and a pull request must be submitted in order to integrate the changes
into the main ContextLab fork.

# Using the bibtex file as a common bibliography for all *local* LaTeX files

## General Unix/Linux Setup (Command Line Compilation)
1. Check out this repository to your home directory
2. Add the following lines to your `~/.bash_profile` (or `~/.zshrc`, etc.):
```
export TEXINPUTS=~/CDL-bibliography:$TEXINPUTS
export BIBINPUTS=~/CDL-bibliography:$BIBINPUTS
export BSTINPUTS=~/CDL-bibliography:$BSTINPUTS
```
3. Run (in terminal): `source ~/.bash_profile`
4. In your .tex file, use the line `\bibliography{cdl}` to generate a bibliography using the citation keys that were defined in memlab.bib and used in the current file.
5. To compile your document (filename.tex), generate a .bib (bibliography) file (filename.bib), and a pdf (filename.pdf), run:
```
latex filename
bibtex filename
latex filename
latex filename
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
You can use [git submodules](https://blog.github.com/2016-02-01-working-with-submodules/) to maintain a reference to the cdl.bib file in this repository that you can easily keep in sync with latest version.  This avoids the need to maintain a separate .bib file in each Overleaf project.

To set this up, you first need to access the GitHub repository associated with your Overleaf project.  Instructions may be found [here](https://www.overleaf.com/learn/how-to/How_do_I_connect_an_Overleaf_project_with_a_repo_on_GitHub,_GitLab_or_BitBucket%3F).
1. Clone your Overleaf project's GitHub repository to your local computer
2. Navigate to the repository's directory (in Terminal) and then run
```
git submodule add https://github.com/ContextLab/CDL-bibliography.git
```
3. Inside your .tex source file, change the `\bibliography{cdl}` line to `\bibliography{CDL-bibliography/cdl}`.  Now the LaTeX compiler will reference the copy of memlab.bib contained in the CDL-bibliography repository, rather than your (potentially separately maintained) local copy.
4. Commit your changes (`git commit -a -m "added CDL bibliography as a submodule"`) and then push them (`git push`).  Your project should now be updated on Overleaf, and the automatic compiler should now have access to memlab.bib.
5. To update your local copy, or to pull changes from the CDL-bibliography repository, run `git pull --recurse-submodules` inside your Overleaf project's repository directory.  Then `git push` your changes to upload them back onto Overleaf.
6. When you clone a fresh repository that includes this repository (or others) as a submodule, run the following commands to download the contents of the submodule repositories:
```
git submodule init
git submodule update
```

# Acknowledgements
This bibtex file is built on a large bibtex file authored by Michael Kahana's
[Computational Memory Lab at the University of Pennsylvania](http://memory.psych.upenn.edu).  
However, this version is not kept in sync with the CML's version.  [Several members](https://github.com/ContextLab/CDL-bibliography/graphs/contributors) of the [Contextual Dynamics Lab](www.context-lab.com/) have contributed to the current version.

This repository is provided as a courtesy, and we make no claims with respect to accuracy, completeness, etc.
