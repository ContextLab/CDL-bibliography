# CDL-bibliography

The main bibtex file ([cdl.bib](https://raw.githubusercontent.com/ContextLab/CDL-bibliography/master/cdl.bib)) is shared by all documents produced by the [Contextual Dynamics Lab](http://www.context-lab.com) at [Dartmouth College](http://www.dartmouth.edu).

## What can I use this repo for?
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
You may find the bibtex checker tools useful for:
- Verifying the integrity of a .bib file
- Autocorrecting a .bib file (use with caution!)
- Automatically generating change logs and commit messages

### Installation
The bibtex checker has only been tested on MacOS, but it will probably work without modification on other Unix systems, and with minor modification on Windows systems.

To install the bibtex checker, you must first have a recent version of Python (3.5+) and [pip](https://pip.pypa.io/en/stable/installing/).  After cloning this repository, install the dependencies by running:

```bash
pip install -r requirements.txt
```

### Overview

The included checker has three general functions: `verify`, `compare`, and `commit`:
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

# Suggested workflow

After making changes to `cdl.bib` (manually, using
[bibdesk](https://bibdesk.sourceforge.io/), etc.), please follow the suggested
workflow below in order to safely update the shared lab resource:

1. Verify the integrity of the modified .bib file (correct any changes until this passes):
```bash
python bibcheck.py verify --verbose cdl.bib
```
2. Generate a change log and commit your changes:
```bash
python bibcheck.py commit --verbose
```
3. Push your changes to your fork:
```bash
git push
```
4. Create a pull request for pulling your changes into the ContextLab fork

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
- Publisher names must be written out in full.  Ampersands ("&") must be converted to "and".
- Addresses must be formatted properly:
  - State names and non-US countries are abbreviated with two-letter codes (e.g., "New York, New York" should be "New York, NY")
  - Address names should be written out in full (e.g., "NY, NY" should be "New York, NY")
  - Abbreviations should not contain periods (".")
- Only the following (standard) fields are allowed: year, volume, title, pages, number, journal, author, booktitle, publisher, editor, school, chapter, address, organization
- To override autoformatting or checks for a given entry, add an additional field, "force" to that bibtex entry and set its value to "True".  No checks will be performed for that entry.  (This is useful if the above rules cannot be properly applied to a given entry.)

If errors are found, they are printed to the terminal along with suggested corrections (if available).

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

### Credit
This bibtex file is built on a large bibtex file authored by Michael Kahana's
[Computational Memory Lab at the University of Pennsylvania](http://memory.psych.upenn.edu).  
However, this version is not kept in sync with the CML's version.  This file is
provided as a courtesy, and we make no claims with respect to accuracy,
completeness, etc.

# Using the bibtex file as a common bibliography for all *local* LaTeX files
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
